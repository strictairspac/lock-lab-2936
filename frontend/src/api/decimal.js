import {api} from './client.js';
// v2 小数接口仅在 decimal 模式生效；integer 模式下后端返回 409。
export const decimalApi={
  createSample:data=>api('/v2/samples','POST',data),
  updateSample:(id,data)=>api('/v2/samples/'+id,'PUT',data),
  createTransfer:data=>api('/v2/transfers','POST',data),
};
