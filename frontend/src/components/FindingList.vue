<template>
  <el-empty v-if="!items.length" description="本次未发现需处理的问题或变化" :image-size="70" />
  <div v-else class="findings"><article v-for="(item,index) in items" :key="index" class="finding">
    <div><el-tag size="small" :type="tagType(item.status)">{{ label(item.status) }}</el-tag><b>{{ item.category }}</b><span>{{ item.message }}</span></div>
    <button v-for="(source,position) in item.sources" :key="position" class="source" type="button" @click="emit('locate',source)">
      {{ documents.find(doc=>doc.id===source.document_id)?.filename??`文档 ${source.document_id}` }} · {{ source.page_number?`第 ${source.page_number} 页`:source.paragraph_index!=null?`段落 ${source.paragraph_index+1}`:'页面' }}：{{ source.quote??'查看原文' }} ↗
    </button>
  </article></div>
</template>

<script setup lang="ts">
import type { AnalysisFinding, AnalysisSource, DocumentItem } from "@/types";
defineProps<{items:AnalysisFinding[];documents:DocumentItem[]}>();
const emit=defineEmits<{(e:"locate",source:AnalysisSource):void}>();
function label(value:string){return ({resolved:"已解决",remaining:"仍存在",new:"新增",uncertain:"待确认",changed:"已变化",replace:"已修改",insert:"新增",delete:"删除",missing:"缺失",ambiguous:"待确认",duplicate:"重复",gap:"缺号",out_of_order:"顺序不符"} as Record<string,string>)[value]??value;}
function tagType(status:string):"success"|"danger"|"warning"|"info"{return status==="resolved"?"success":["remaining","new","missing","duplicate","out_of_order"].includes(status)?"danger":["uncertain","ambiguous","gap"].includes(status)?"warning":"info";}
</script>

<style scoped>
.finding{padding:12px;margin:10px 0;border:1px solid #e8edf5;border-radius:8px;font-size:13px}.finding>div{display:flex;flex-wrap:wrap;gap:9px;align-items:center}.source{display:block;width:100%;padding:9px;margin-top:8px;border:0;border-left:3px solid #6b85df;background:#f3f6fd;color:#3c507d;text-align:left;cursor:pointer;overflow-wrap:anywhere}
</style>
