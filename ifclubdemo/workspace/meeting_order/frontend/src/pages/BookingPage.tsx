import { useCallback, useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import BookingForm from "../components/BookingForm";
import BookingList from "../components/BookingList";
import RoomList from "../components/RoomList";
import RulesPanel from "../components/RulesPanel";
import { apiGet, apiPost } from "../api/client";
import type { Booking, CreateBookingRequest, Room } from "../types";

export default function BookingPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");

  const refreshBookings = useCallback(async () => {
    const data = await apiGet<Booking[]>("/bookings");
    setBookings(data);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const r = await apiGet<Room[]>("/rooms");
        setRooms(r);
        await refreshBookings();
      } catch {
        setError("加载失败：请确认后端 /api/v1 可用");
      }
    })();
  }, []);

  const onSubmit = async (payload: CreateBookingRequest) => {
    setError("");
    try {
      await apiPost<Booking>("/bookings", payload);
      await refreshBookings();
    } catch (e) {
      if (e instanceof Error && e.message.includes("BOOKING_CONFLICT")) {
        setError("预订失败：时间冲突或会议室不可用");
      } else {
        setError(e instanceof Error ? e.message : "预订失败");
      }
    }
  };

  return (
    <div>
      <ErrorBanner message={error} />
      <div className="panel">
        <h2>提交预订</h2>
        <BookingForm rooms={rooms} onSubmit={onSubmit} />
      </div>
      <div className="panel">
        <h2>会议室</h2>
        <RoomList rooms={rooms} />
      </div>
      <div className="panel">
        <h2>已有预订</h2>
        <BookingList bookings={bookings} />
      </div>
      <RulesPanel />
    </div>
  );
}