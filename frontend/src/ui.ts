import type { App } from 'vue';
import { ElAlert } from 'element-plus/es/components/alert/index';
import { ElAside, ElContainer, ElHeader, ElMain } from 'element-plus/es/components/container/index';
import { ElButton } from 'element-plus/es/components/button/index';
import { ElCard } from 'element-plus/es/components/card/index';
import { ElCheckbox, ElCheckboxButton, ElCheckboxGroup } from 'element-plus/es/components/checkbox/index';
import { ElDialog } from 'element-plus/es/components/dialog/index';
import { ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus/es/components/dropdown/index';
import { ElEmpty } from 'element-plus/es/components/empty/index';
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index';
import { ElInput } from 'element-plus/es/components/input/index';
import { ElInputNumber } from 'element-plus/es/components/input-number/index';
import { ElOption, ElSelect } from 'element-plus/es/components/select/index';
import { ElRadio, ElRadioButton, ElRadioGroup } from 'element-plus/es/components/radio/index';
import { ElResult } from 'element-plus/es/components/result/index';
import { ElSkeleton } from 'element-plus/es/components/skeleton/index';
import { ElSwitch } from 'element-plus/es/components/switch/index';
import { ElTabPane, ElTabs } from 'element-plus/es/components/tabs/index';
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index';
import { ElTag } from 'element-plus/es/components/tag/index';
import { ElTooltip } from 'element-plus/es/components/tooltip/index';
import { ElUpload } from 'element-plus/es/components/upload/index';
import { ElLoading } from 'element-plus/es/components/loading/index';

// 只注册项目使用的组件，让构建器移除未使用的组件模块。
export default { install(app: App) {
  for (const component of [ElAlert, ElAside, ElButton, ElCard, ElCheckbox, ElCheckboxButton,
    ElCheckboxGroup, ElContainer, ElDialog, ElDropdown, ElDropdownItem, ElDropdownMenu,
    ElEmpty, ElForm, ElFormItem, ElHeader, ElInput, ElInputNumber, ElMain, ElOption,
    ElRadio, ElRadioButton, ElRadioGroup, ElResult, ElSelect, ElSkeleton, ElSwitch,
    ElTabPane, ElTable, ElTableColumn, ElTabs, ElTag, ElTooltip, ElUpload]) {
    app.component(component.name!, component);
  }
  app.directive('loading', ElLoading.directive);
} };
