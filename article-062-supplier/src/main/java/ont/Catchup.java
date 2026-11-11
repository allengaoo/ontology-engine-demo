package ont;

import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Duration;
import java.util.Properties;
import java.util.concurrent.atomic.AtomicBoolean;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;

/** 提交成功之后追平副本。同一条编辑处理两次，结果相同。 */
public final class Catchup implements Runnable {
    private final AtomicBoolean paused = new AtomicBoolean(false);
    private final AtomicBoolean ready = new AtomicBoolean(false);
    private final AtomicBoolean stopped = new AtomicBoolean(false);
    private volatile KafkaConsumer<String, String> consumer;

    public void pause() {
        paused.set(true);
        Log.line("追平已暂停。已取到的编辑先不写副本");
    }

    public void resume() {
        paused.set(false);
        Log.line("追平已恢复");
    }

    public void close() {
        stopped.set(true);
        paused.set(false);
        KafkaConsumer<String, String> current = consumer;
        if (current != null) {
            current.wakeup();
        }
    }

    public void awaitReady() throws InterruptedException {
        for (int i = 0; i < 300 && !ready.get(); i++) {
            Thread.sleep(100);
        }
        if (!ready.get()) {
            throw new IllegalStateException("追平线程没有开始消费");
        }
    }

    @Override
    public void run() {
        consumer = new KafkaConsumer<>(consumerProps());
        consumer.subscribe(java.util.List.of(Config.TOPIC));
        ready.set(true);
        Log.line("追平开始消费 " + Config.TOPIC);
        try {
            while (!stopped.get()) {
                pollOnce();
            }
        } finally {
            consumer.close();
        }
    }

    private void pollOnce() {
        try {
            ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(200));
            records.forEach(record -> holdThenApply(record.value()));
        } catch (org.apache.kafka.common.errors.WakeupException ex) {
            if (!stopped.get()) {
                throw ex;
            }
        }
    }

    public synchronized boolean apply(String json) {
        String eventId = OrderIndex.string(json, "event_id");
        if (seen(eventId)) {
            Log.line("追平 事件 " + eventId + "：已经处理过，副本保持不变");
            return false;
        }
        int poId = OrderIndex.number(json, "po_id");
        int supplierId = OrderIndex.number(json, "supplier_id");
        String status = OrderIndex.string(json, "status");
        Log.line("追平 事件 " + eventId + "：采购单 " + poId
                + " 副本写成供应商 " + Log.supplier(supplierId) + "，状态 " + status);
        writeCopies(poId, supplierId, status);
        mark(eventId);
        return true;
    }

    private void holdThenApply(String json) {
        if (paused.get()) {
            Log.line("追平暂停中，这条编辑先留在消费端");
            while (paused.get() && !stopped.get()) {
                sleep();
            }
        }
        if (stopped.get()) {
            return;
        }
        apply(json);
    }

    private static void writeCopies(int poId, int supplierId, String status) {
        try {
            OrderIndex.put(poId, supplierId, status);
            try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "");
                    var statement = conn.prepareStatement(
                            "INSERT INTO ont.purchase_order (id, supplier_id, status) VALUES (?, ?, ?)")) {
                statement.setInt(1, poId);
                statement.setInt(2, supplierId);
                statement.setString(3, status);
                statement.execute();
            }
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static boolean seen(String eventId) {
        try (Connection conn = Databases.purchase()) {
            return Sql.queryString(
                    conn, "SELECT event_id FROM consumed_event WHERE event_id = ?", eventId) != null;
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static void mark(String eventId) {
        try (Connection conn = Databases.purchase()) {
            conn.setAutoCommit(false);
            Sql.exec(conn, "INSERT INTO consumed_event (event_id) VALUES (?) ON CONFLICT DO NOTHING", eventId);
            conn.commit();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static Properties consumerProps() {
        Properties props = new Properties();
        props.put("bootstrap.servers", Config.KAFKA);
        props.put("group.id", "catchup-java");
        props.put("auto.offset.reset", "earliest");
        props.put("enable.auto.commit", "true");
        props.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
        props.put("value.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
        return props;
    }

    private static void sleep() {
        try {
            Thread.sleep(50);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }
}
