import {adminApi} from '../api/admin.js';
import {interfaceStore} from '../stores/interface.js';
import {esc} from '../utils/html.js';

function jobRows(jobs){
  const names={samples:'样本台账 samples',transfers:'流转申请 transfers'};
  return Object.keys(names).map(key=>{
    const j=jobs[key];
    if(!j) return `<tr><td>${names[key]}</td><td colspan="4">尚未开始回填</td></tr>`;
    return `<tr><td>${names[key]}</td><td>${j.status==='completed'?'<span class="badge completed">已完成</span>':'<span class="badge running">进行中</span>'}</td><td>${j.done_rows} / ${j.total_rows}</td><td>跳过 ${j.skipped_rows}</td><td>断点 last_id=${j.last_id}</td></tr>`;
  }).join('');
}

export function adminPage(backfill){
  const decimal=interfaceStore.decimal;
  return `<div class="split"><section>
    <div class="section-top"><h2>接口模式</h2><span>VERSION ${interfaceStore.version}</span></div>
    <div class="verdict"><div class="verdict-icon">${decimal?'②':'①'}</div><div>
      <span class="eyebrow">INTERFACE MODE</span>
      <h2>${decimal?'小数接口 decimal 已生效':'整数接口 integer 生效中'}</h2>
      <p>${decimal?'样本量与移交量两个接口同时支持两位小数；回退后立即恢复整数办理。':'升级期间旧接口照常按整数办理；历史数据回填完成后两个接口一起切换。'}</p>
    </div></div>
    <div class="section-top"><h2>历史回填进度</h2><span>${backfill.all_completed?'全部完成':'分批进行中 · 中断可续跑'}</span></div>
    <div class="table-wrap"><table><thead><tr><th>数据表</th><th>状态</th><th>已回填 / 总量</th><th>业务优先跳过</th><th>断点</th></tr></thead>
    <tbody>${jobRows(backfill.jobs)}</tbody></table></div>
    <div class="notice">回填与并发业务写入相撞时，业务事务持锁的行本批自动跳过（SKIP LOCKED），业务提交后下一轮补标记，数量始终以业务写入为准。</div>
  </section>
  <section class="form-panel"><span class="eyebrow">ADMIN OPS</span><h2>切换与回填操作</h2>
    <form id="backfill-form"><button class="primary" type="submit">推进一批回填 ↻</button></form>
    <p class="help">每点一次各表处理一批（默认 200 行/批）；也可离线运行 <code>python -m scripts.backfill_history</code> 循环续跑。</p>
    <form id="switch-form" style="margin-top:24px">
      <button class="primary" type="submit" ${decimal?'disabled':''}>两个接口一起切换到小数 ↗</button>
    </form>
    <p class="help">前置条件：两张表历史数据全部回填。条件不满足时切换失败并沿用整数。</p>
    <form id="rollback-form" style="margin-top:24px">
      <button class="primary" type="submit" ${decimal?'':'disabled'}>回退到整数接口 ↺</button>
    </form>
    <p class="help">回退与小数写入共用同一把事务咨询锁：谁先办成按谁的结果走，另一边收到 409 冲突报错。</p>
  </section></div>`;
}
