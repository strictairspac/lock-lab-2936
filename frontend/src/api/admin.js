import {api} from './client.js';
export const adminApi={
  currentMode:()=>api('/interface/current'),
  switchDecimal:()=>api('/interface/switch-decimal','POST'),
  rollbackInteger:()=>api('/interface/rollback-integer','POST'),
  backfillStatus:()=>api('/backfill/status'),
  backfillRun:()=>api('/backfill/run','POST'),
};
