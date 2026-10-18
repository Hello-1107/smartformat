"""审查准确性、候选确认和数据生命周期回归；全部使用合成文档与模拟 AI。"""
import io
from unittest.mock import patch

import pytest
from docx import Document
from docx.enum.section import WD_SECTION
from docx.shared import Cm, Pt
from sqlalchemy import select, func, text

from app.database import SessionLocal
from app.models import CheckResult
from app.models.content_review import ContentReview
from app.models.template_audit import TemplateReview
from app.schemas.rule import RuleSet, ScopeRule, FontRule, ParagraphRule, PageRule
from app.schemas.document import ParsedDocument, ParsedParagraph, FontInfo
from app.schemas.content_review import ContentReviewResult
from app.services.checker import run_check
from app.services.docx_parser import parse_docx
from app.services.document_rule_extractor import extract_candidates, extract_ruleset_from_document
from app.services.revision_copy import build_revised_copy, is_repairable_format


def save_doc(doc, path):
    doc.save(path)
    return path


def doc_bytes(doc=None):
    if doc is None:
        doc = Document()
        doc.add_paragraph('合成正文').runs[0].font.size = Pt(14)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def upload(client, headers, workspace):
    response = client.post('/api/documents', params={'workspace_id':workspace,'filename':'sample.docx'}, content=doc_bytes(), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_title_independent_and_candidates_require_selection(tmp_path) -> None:
    doc = Document()
    doc.add_heading('大标题', 0).runs[0].font.size = Pt(28)
    doc.add_heading('一级标题A', 1).runs[0].font.size = Pt(18)
    doc.add_heading('一级标题B', 1).runs[0].font.size = Pt(16)
    path = save_doc(doc, tmp_path/'input.docx')
    parsed = parse_docx(path)
    assert parsed.paragraphs[0].is_title and parsed.paragraphs[0].level is None
    result = extract_candidates(path, filename='团队标准.docx')
    assert result.ruleset.name == '团队标准'
    assert len(result.candidates['title']) == 1
    assert {c.style.font.size for c in result.candidates['h1']} == {16,18}
    with pytest.raises(ValueError, match='候选'):
        extract_ruleset_from_document(path)


def test_unknown_values_and_empty_rules_never_pass() -> None:
    parsed = ParsedDocument(filename='unknown', paragraphs=[ParsedParagraph(index=0,text='正文',style_name='Normal',font=FontInfo())])
    violations, summary = run_check(parsed, RuleSet(name='r', body=ScopeRule(font=FontRule(size=12))))
    assert not summary.compliant and summary.status == 'unknown' and summary.unknown == 1
    assert not is_repairable_format(violations[0])
    with pytest.raises(ValueError, match='有效检查项'):
        run_check(parsed, RuleSet(name='empty'))


def test_mixed_run_repair_only_changes_selected_run(tmp_path) -> None:
    doc = Document()
    p = doc.add_paragraph()
    p.add_run('长段正文应该保持原状').font.size = Pt(12)
    p.add_run('异常').font.size = Pt(30)
    path = save_doc(doc,tmp_path/'mixed.docx')
    issues, _ = run_check(parse_docx(path),RuleSet(name='r',body=ScopeRule(font=FontRule(size=12))))
    assert len(issues) == 1 and issues[0].run_index == 1
    output = Document(io.BytesIO(build_revised_copy(path,'mixed.docx',issues,[])))
    assert [r.font.size.pt for r in output.paragraphs[0].runs] == [12,12]
    assert Document(path).paragraphs[0].runs[1].font.size.pt == 30


def test_multisection_check_and_scoped_repair(tmp_path) -> None:
    doc=Document(); doc.add_paragraph('正文')
    doc.sections[0].left_margin=Cm(2.5)
    doc.add_section(WD_SECTION.NEW_PAGE).left_margin=Cm(6)
    path=save_doc(doc,tmp_path/'sections.docx')
    issues,_=run_check(parse_docx(path),RuleSet(name='r',page=PageRule(margin_left_cm=2.5)))
    assert len(issues)==1 and issues[0].section_index==1
    revised=Document(io.BytesIO(build_revised_copy(path,'sections.docx',issues,[])))
    assert round(revised.sections[0].left_margin.cm,1)==2.5
    assert round(revised.sections[1].left_margin.cm,1)==2.5


def test_inherited_headings_numbering_and_spacing_types(tmp_path) -> None:
    from docx.enum.style import WD_STYLE_TYPE
    doc=Document()
    style=doc.styles.add_style('Custom Section',WD_STYLE_TYPE.PARAGRAPH)
    style.base_style=doc.styles['Heading 2']
    doc.add_paragraph('继承标题',style)
    doc.add_paragraph('项目', 'List Bullet')
    doc.add_paragraph('编号', 'List Number')
    p=doc.add_paragraph('固定行距');p.paragraph_format.line_spacing=Pt(18)
    path=save_doc(doc,tmp_path/'styles.docx')
    parsed=parse_docx(path)
    assert parsed.paragraphs[0].level==2
    assert parsed.paragraphs[1].bullet and parsed.paragraphs[2].numbered
    assert parsed.paragraphs[3].line_spacing==18 and parsed.paragraphs[3].line_spacing_kind=='exact'
    issues,_=run_check(parsed,RuleSet(name='r',body=ScopeRule(paragraph=ParagraphRule(line_spacing=1.5))))
    assert any(v.paragraph_index==3 and v.field=='line_spacing' for v in issues)


def test_candidate_api_does_not_save_rule_before_confirmation(client,auth,workspace) -> None:
    headers,_=auth
    response=client.post('/api/rules/document-template-candidates',params={'workspace_id':workspace,'filename':'真实模板名.docx'},content=doc_bytes(),headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['ruleset']['name']=='真实模板名'
    assert client.get('/api/rules',params={'workspace_id':workspace},headers=headers).json()==[]


def test_deleting_document_removes_all_review_history(client,auth,workspace,monkeypatch) -> None:
    headers,_=auth; document_id=upload(client,headers,workspace)
    rule=client.post('/api/rules/manual',json={'workspace_id':workspace,'ruleset':{'name':'r','body':{'font':{'size':12}}}},headers=headers).json()
    check=client.post('/api/checks',json={'workspace_id':workspace,'document_id':document_id,'rule_id':rule['id']},headers=headers)
    assert check.status_code==201,check.text
    monkeypatch.setattr('app.api.content_reviews.review_content',lambda *_: ContentReviewResult(summary='完成',issues=[]))
    assert client.post('/api/content-reviews',json={'workspace_id':workspace,'document_id':document_id},headers=headers).status_code==201
    template=client.post('/api/template-audits/template',params={'workspace_id':workspace},content=doc_bytes(),headers=headers).json()
    publish={'workspace_id':workspace,'name':'t','blocks':template['config']['blocks']}
    assert client.put('/api/template-audits/current',json=publish,headers=headers).status_code==200
    assert client.post('/api/template-audits/reviews',json={'workspace_id':workspace,'document_id':document_id},headers=headers).status_code==201
    assert client.delete(f'/api/documents/{document_id}',headers=headers).status_code==204
    with SessionLocal() as db:
        assert db.execute(text('PRAGMA foreign_keys')).scalar()==1
        for model in (CheckResult, ContentReview, TemplateReview):
            assert db.scalar(select(func.count()).select_from(model))==0
    replacement=upload(client,headers,workspace)
    assert client.get('/api/checks',params={'workspace_id':workspace},headers=headers).json()==[]
    assert client.get(f'/api/documents/{replacement}/download',headers=headers).status_code==200


def test_failed_delete_preserves_original(client,auth,workspace,monkeypatch) -> None:
    from sqlalchemy.orm import Session
    headers,_=auth; document_id=upload(client,headers,workspace)
    original=client.get(f'/api/documents/{document_id}/download',headers=headers).content
    def fail(*_):raise RuntimeError('simulated commit failure')
    with monkeypatch.context() as m:
        m.setattr(Session,'commit',fail)
        with pytest.raises(RuntimeError,match='simulated'):
            client.delete(f'/api/documents/{document_id}',headers=headers)
    assert client.get(f'/api/documents/{document_id}/download',headers=headers).content==original


def test_published_template_is_immutable(client,auth,workspace) -> None:
    headers,_=auth
    t=client.post('/api/template-audits/template',params={'workspace_id':workspace},content=doc_bytes(),headers=headers).json()
    body={'workspace_id':workspace,'template_id':t['id'],'name':'初版','blocks':t['config']['blocks']}
    first=client.put('/api/template-audits/current',json=body,headers=headers).json()
    body['name']='修改版'
    second=client.put('/api/template-audits/current',json=body,headers=headers).json()
    assert second['id']!=first['id'] and second['version']>first['version']
    assert client.get(f"/api/template-audits/templates/{first['id']}",headers=headers).json()['name']=='初版'
    assert client.put('/api/template-audits/current',json=body,headers=headers).status_code==409


@pytest.mark.parametrize('ruleset',[
    {'name':' ','body':{'font':{'size':12}}},
    {'name':'r','body':{'font':{'size':-12}}},
    {'name':'r','body':{'font':{'color':'bad'}}},
    {'name':'r','page':{'width_cm':-10}},
    {'name':'r','heading_structure':{'max_level':99}},
])
def test_rule_validation(client,auth,workspace,ruleset) -> None:
    headers,_=auth
    assert client.post('/api/rules/manual',json={'workspace_id':workspace,'ruleset':ruleset},headers=headers).status_code==422


def test_upload_limits_and_invalid_token(client,auth,workspace,monkeypatch) -> None:
    from app.config import settings
    headers,_=auth
    monkeypatch.setattr(settings,'max_upload_bytes',10)
    assert client.post('/api/documents',params={'workspace_id':workspace},content=b'x'*11,headers=headers).status_code==413
    from app.security import decode_access_token,TokenError
    with pytest.raises(TokenError):decode_access_token('x.é.x')


def test_empty_document_cannot_pass_body_rules() -> None:
    _,summary=run_check(ParsedDocument(filename='empty'),RuleSet(name='r',body=ScopeRule(font=FontRule(size=12))))
    assert not summary.compliant and summary.unknown==1


def test_chunked_review_preserves_source_indexes_and_validates_limits(monkeypatch) -> None:
    from app.services import deepseek_content
    from app.schemas.content_review import ContentParagraph, ContentIssue
    calls=[]
    def fake_review(paragraphs,instructions=''):
        assert len(paragraphs)<=1500 and sum(len(p.text) for p in paragraphs)<=30000
        calls.append([p.index for p in paragraphs])
        first=paragraphs[0]
        return ContentReviewResult(summary='合成结果',issues=[ContentIssue(paragraph_index=first.index,quote=first.text[:10],category='措辞',severity='建议',reason='合成问题',suggestion='合成建议')])
    monkeypatch.setattr(deepseek_content,'review_content',fake_review)
    result=deepseek_content.review_content_chunked([ContentParagraph(index=i*10,text='合成'*10000) for i in range(3)])
    assert len(calls)==4
    assert {issue.paragraph_index for issue in result.issues}=={0,10,20}
    assert '节选' in result.summary
    with pytest.raises(ValueError):deepseek_content.validate_chunked([ContentParagraph(index=0,text='x'*60001)])


def test_invalid_related_reference_fails_instead_of_disappearing(monkeypatch) -> None:
    from test_content_review import fake_response
    from app.services.deepseek_content import review_content
    from app.schemas.content_review import ContentParagraph
    fake_response(monkeypatch,{'summary':'合成','issues':[{'paragraph_index':0,'quote':'原文','category':'逻辑','severity':'重要','reason':'合成原因','suggestion':'合成建议','related_references':[{'paragraph_index':9,'quote':'不存在'}]}]})
    with pytest.raises(ValueError,match='关联依据'):
        review_content([ContentParagraph(index=0,text='原文')])


def test_structural_changes_disable_template_repair(tmp_path) -> None:
    from app.services.template_audit import extract_template_configuration,review_against_template
    template=Document();template.add_heading('标准标题',1);template.add_paragraph('内容')
    config=extract_template_configuration(save_doc(template,tmp_path/'template.docx'))
    target=Document();target.add_paragraph('新增段落');target.add_heading('标准标题',1);target.add_paragraph('内容')
    result=review_against_template(config,save_doc(target,tmp_path/'target.docx'))
    assert result.issues and not result.compliant
    assert all(not issue.repairable for issue in result.issues)


def test_check_snapshots_and_history_pagination(client,auth,workspace) -> None:
    headers,_=auth;document_id=upload(client,headers,workspace)
    rule=client.post('/api/rules/manual',json={'workspace_id':workspace,'ruleset':{'name':'v1','body':{'font':{'size':12}}}},headers=headers).json()
    request={'workspace_id':workspace,'document_id':document_id,'rule_id':rule['id']}
    old=client.post('/api/checks',json=request,headers=headers).json()
    client.put(f"/api/rules/{rule['id']}/ruleset",json={'name':'v2','body':{'font':{'size':16}}},headers=headers)
    latest=client.post('/api/checks',json=request,headers=headers).json()
    assert client.get(f"/api/checks/{old['id']}",headers=headers).json()['ruleset_snapshot']['ruleset']['name']=='v1'
    first=client.get('/api/checks',params={'workspace_id':workspace,'limit':1},headers=headers).json()
    second=client.get('/api/checks',params={'workspace_id':workspace,'limit':1,'before_id':first[0]['id']},headers=headers).json()
    assert first[0]['id']==latest['id'] and second[0]['id']==old['id']
    assert len(client.get('/api/checks',params={'workspace_id':workspace,'latest_only':True},headers=headers).json())==1


def test_production_key_and_login_throttle() -> None:
    from app.config import Settings
    from app.services import login_throttle
    from fastapi import HTTPException
    with pytest.raises(ValueError):Settings(_env_file=None,environment='production',secret_key='dev-secret-change-me-in-production')
    bucket=login_throttle.key('synthetic','limited-user')
    try:
        for _ in range(8):login_throttle.record(bucket,False)
        with pytest.raises(HTTPException) as caught:login_throttle.check(bucket)
        assert caught.value.status_code==429
    finally:login_throttle.record(bucket,True)


def test_conflicting_paragraph_and_run_repairs_are_rejected(tmp_path) -> None:
    from app.schemas.check import Violation
    from app.services.revision_copy import RepairError
    path=tmp_path/'conflict.docx';path.write_bytes(doc_bytes())
    values=dict(scope='body',category='font',field='size',actual=14,message='合成修订',paragraph_index=0)
    with pytest.raises(RepairError,match='冲突'):
        build_revised_copy(path,'conflict.docx',[Violation(**values,expected=12),Violation(**values,expected=16,run_index=0)],[])


def test_draft_keeps_explicitly_selected_published_template(client,auth,workspace) -> None:
    headers,_=auth
    first=client.post('/api/template-audits/template',params={'workspace_id':workspace},content=doc_bytes(),headers=headers).json()
    body={'workspace_id':workspace,'template_id':first['id'],'name':'v1','blocks':first['config']['blocks']}
    assert client.put('/api/template-audits/current',json=body,headers=headers).status_code==200
    second=client.put('/api/template-audits/current',json={**body,'name':'v2'},headers=headers).json()
    assert second['id']!=first['id']
    assert client.post(f"/api/template-audits/versions/{first['id']}/activate",params={'workspace_id':workspace},headers=headers).status_code==200
    assert client.post('/api/template-audits/template',params={'workspace_id':workspace},content=doc_bytes(),headers=headers).status_code==201
    document_id=upload(client,headers,workspace)
    response=client.post('/api/template-audits/reviews',json={'workspace_id':workspace,'document_id':document_id},headers=headers)
    assert response.status_code==201,response.text
    assert response.json()['template_id']==first['id']
    assert response.json()['template_snapshot']['name']=='v1'


def test_document_defaults_are_read_without_changing_variable_fields(tmp_path) -> None:
    from app.services.template_audit import extract_template_configuration
    doc=Document();doc.add_paragraph('用户填写的姓名')
    path=save_doc(doc,tmp_path/'defaults.docx')
    parsed=parse_docx(path)
    assert parsed.paragraphs[0].font.size==11
    assert parsed.paragraphs[0].alignment=='left'
    assert extract_template_configuration(path).blocks[0].mode=='variable'


def test_review_finishing_after_delete_does_not_recreate_history(client,auth,workspace,monkeypatch) -> None:
    headers,_=auth;document_id=upload(client,headers,workspace)
    def fake_review(*_):
        assert client.delete(f'/api/documents/{document_id}',headers=headers).status_code==204
        upload(client,headers,workspace)
        return ContentReviewResult(summary='迟到的合成结果',issues=[])
    monkeypatch.setattr('app.api.content_reviews.review_content',fake_review)
    response=client.post('/api/content-reviews',json={'workspace_id':workspace,'document_id':document_id},headers=headers)
    assert response.status_code==404,response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ContentReview))==0


def test_preview_replaces_input_bookmarks_in_reserved_namespace(tmp_path) -> None:
    from docx.oxml import OxmlElement,parse_xml
    from docx.oxml.ns import qn
    from zipfile import ZipFile
    from app.services.document_content import preview_bytes
    doc=Document();first=doc.add_paragraph('错误位置');doc.add_paragraph('正确位置')
    start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),'9');start.set(qn('w:name'),'sf_content_1')
    end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),'9');first._p.append(start);first._p.append(end)
    path=save_doc(doc,tmp_path/'bookmarks.docx');original=path.read_bytes()
    with ZipFile(io.BytesIO(preview_bytes(path))) as archive:
        root=parse_xml(archive.read('word/document.xml'))
        anchors=root.xpath('//w:bookmarkStart[@w:name="sf_content_1"]')
        assert len(anchors)==1 and '正确位置' in ''.join(anchors[0].getparent().itertext())
    assert path.read_bytes()==original
