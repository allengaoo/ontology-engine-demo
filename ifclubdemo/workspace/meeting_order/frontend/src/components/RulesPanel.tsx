export default function RulesPanel() {
  return (
    <div className="panel">
      <h2>预订规矩</h2>
      <ul>
        <li>结束时间必须晚于开始时间</li>
        <li>同一会议室时段不能重叠（首尾相接可以）</li>
        <li>只能订启用中的会议室</li>
        <li>冲突由系统拒绝，页面只负责提示</li>
        <li>请确保选择的会议室处于启用状态</li>
        <li>预订时请确认时间区间无其他会议安排</li>
      </ul>
    </div>
  );
}