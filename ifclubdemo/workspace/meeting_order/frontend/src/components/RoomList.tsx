import type { Room } from "../types";

export default function RoomList({ rooms }: { rooms: Room[] }) {
  if (!rooms.length) {
    return <p className="muted">暂无会议室（待初始化）</p>;
  }
  return (
    <ul className="list">
      {rooms.map((r) => (
        <li key={r.id}>
          {r.name} · 约 {r.capacity} 人{" "}
          {!r.is_active && <span className="badge-off">停用</span>}
        </li>
      ))}
    </ul>
  );
}