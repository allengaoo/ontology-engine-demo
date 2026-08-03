export type Room = {
  id: number;
  name: string;
  capacity: number;
  is_active: boolean;
};

export type Booking = {
  id?: number | null;
  room_id: number;
  title: string;
  booker: string;
  start_at: string;
  end_at: string;
};

export type CreateBookingRequest = {
  room_id: number;
  title: string;
  booker: string;
  start_at: string;
  end_at: string;
};
