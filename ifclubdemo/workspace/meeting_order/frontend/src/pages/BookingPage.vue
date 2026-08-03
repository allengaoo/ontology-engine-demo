vue
<template>
  <div class="booking-page">
    <h1>会议室预订</h1>
    <form @submit.prevent="submitBooking">
      <div>
        <label>会议室:</label>
        <select v-model="form.roomId" required>
          <option value="">请选择会议室</option>
          <option v-for="room in rooms" :key="room.id" :value="room.id">
            {{ room.name }}
          </option>
        </select>
      </div>
      <div>
        <label>标题:</label>
        <input v-model="form.title" type="text" required />
      </div>
      <div>
        <label>预订人:</label>
        <input v-model="form.booker" type="text" required />
      </div>
      <div>
        <label>开始时间:</label>
        <input v-model="form.startAt" type="datetime-local" required />
      </div>
      <div>
        <label>结束时间:</label>
        <input v-model="form.endAt" type="datetime-local" required />
      </div>
      <button type="submit">提交预订</button>
    </form>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';

const form = ref({
  roomId: '',
  title: '',
  booker: '',
  startAt: '',
  endAt: ''
});

const rooms = ref([]);
const error = ref('');

const apiUrl = '/api/v1';

const fetchRooms = async () => {
  try {
    const response = await axios.get(`${apiUrl}/rooms`);
    rooms.value = response.data;
  } catch (err) {
    error.value = '获取会议室列表失败';
  }
};

const submitBooking = async () => {
  try {
    const bookingData = {
      room_id: parseInt(form.value.roomId),
      title: form.value.title,
      booker: form.value.booker,
      start_at: form.value.startAt,
      end_at: form.value.endAt
    };

    await axios.post(`${apiUrl}/bookings`, bookingData);
    alert('预订成功');
    form.value = {
      roomId: '',
      title: '',
      booker: '',
      startAt: '',
      endAt: ''
    };
  } catch (err) {
    if (err.response && err.response.status === 409) {
      error.value = err.response.data.detail.message;
    } else {
      error.value = '预订失败';
    }
  }
};

onMounted(() => {
  fetchRooms();
});
</script>

<style scoped>
.booking-page {
  padding: 20px;
}

form div {
  margin-bottom: 10px;
}

.error {
  color: red;
}
</style>