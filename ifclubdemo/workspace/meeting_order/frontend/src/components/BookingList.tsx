import type { Booking } from "../types";

export default function BookingList({ bookings }: { bookings: Booking[] }) {
  if (!bookings.length) {
    return <p className="muted">暂无预订</p>;
  }
  return (
    <ul className="list">
      {bookings.map((b, i) => (
        <li key={b.id ?? i}>
          房间 #{b.room_id} · {b.title} · {b.booker} · {b.start_at} → {b.end_at}
        </li>
      ))}
    </ul>
  );
}