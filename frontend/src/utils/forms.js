export function formValues(form, numbers=[]){const values=Object.fromEntries(new FormData(form));for(const key of numbers)values[key]=Number(values[key]);return values;}
// 两位小数刻度：去掉多余的 0 展示，如 12.30 -> 12.3、120 -> 120；表格仍由后端保证两位存储。
export function qty(value){const n=Number(value);return Number.isFinite(n)?String(n):String(value??'');}
