import type { CreateBookingRequest, Room } from "../types";

type Props = {
  rooms: Room[];
  onSubmit: (data: CreateBookingRequest) => void | Promise<void>;
};

function toApiDateTime(value: string): string {
  const v = (value || "").trim();
  return v.length === 16 ? `${v}:00` : v;
}

export default function BookingForm({ rooms, onSubmit }: Props) {
  // Filter rooms that are active and available (not booked during the selected time)
  const availableRooms = rooms.filter(
    (room) =>
      room.is_active &&
      !room.bookings?.some((booking) => {
        // Simple time overlap check (in a real app, this would be more robust)
        return (
          booking.start_at <= booking.end_at &&
          booking.end_at >= booking.start_at
        );
      })
  );

  return (
    <form
      className="booking-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        const startAt = toApiDateTime(String(fd.get("start_at") || ""));
        const endAt = toApiDateTime(String(fd.get("end_at") || ""));
        
        // Validate time range
        if (startAt >= endAt) {
          alert("结束时间必须晚于开始时间");
          return;
        }

        await onSubmit({
          room_id: Number(fd.get("room_id")),
          title: String(fd.get("title") || "").trim(),
          booker: String(fd.get("booker") || "").trim(),
          start_at: startAt,
          end_at: endAt,
        });
      }}
    >
      <label>
        会议室
        <select name="room_id" required defaultValue="">
          <option value="" disabled>
            请选择
          </option>
          {availableRooms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        会议主题
        <input name="title" placeholder="主题" required />
      </label>
      <label>
        预订人
        <input name="booker" placeholder="姓名" required />
      </label>
      <label>
        开始时间
        <input name="start_at" type="datetime-local" required />
      </label>
      <label>
        结束时间
        <input name="end_at" type="datetime-local" required />
      </label>
      <button type="submit">提交预订</button>
    </form>
  );
}