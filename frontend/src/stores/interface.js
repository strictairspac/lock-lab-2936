import {adminApi} from '../api/admin.js';
// 接口模式全局状态：integer=旧整数接口；decimal=样本量/移交量两个小数接口同时生效。
export const interfaceStore={
  mode:'integer',version:0,
  async refresh(){const d=await adminApi.currentMode();this.mode=d.mode;this.version=d.version;return d;},
  get decimal(){return this.mode==='decimal';},
};
