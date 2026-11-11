package ont;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public final class OrderIndex {
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private OrderIndex() {}

    public static void recreate() throws Exception {
        send("DELETE", "/" + Config.INDEX, null);
        send("PUT", "/" + Config.INDEX, "{}");
        System.out.println("就绪 Elasticsearch 索引");
    }

    public static void put(int poId, int supplierId, String status) throws Exception {
        String body = "{\"factory_id\":" + Config.FACTORY_ID
                + ",\"supplier_id\":" + supplierId
                + ",\"status\":\"" + status + "\"}";
        send("PUT", "/" + Config.INDEX + "/_doc/" + poId + "?refresh=wait_for", body);
    }

    public static Doc get(int poId) throws Exception {
        HttpResponse<String> response = send("GET", "/" + Config.INDEX + "/_doc/" + poId, null);
        if (response.statusCode() == 404) {
            return null;
        }
        String json = response.body();
        return new Doc(number(json, "supplier_id"), string(json, "status"));
    }

    private static HttpResponse<String> send(String method, String path, String body) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(Config.ES + path))
                .timeout(Duration.ofSeconds(10));
        if (body == null) {
            builder.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            builder.header("Content-Type", "application/json")
                    .method(method, HttpRequest.BodyPublishers.ofString(body));
        }
        return HTTP.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    static int number(String json, String field) {
        String key = "\"" + field + "\":";
        int at = json.indexOf(key);
        int start = at + key.length();
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) {
            end++;
        }
        return Integer.parseInt(json.substring(start, end));
    }

    static String string(String json, String field) {
        String key = "\"" + field + "\":\"";
        int start = json.indexOf(key) + key.length();
        return json.substring(start, json.indexOf('"', start));
    }

    public record Doc(int supplierId, String status) {}
}
