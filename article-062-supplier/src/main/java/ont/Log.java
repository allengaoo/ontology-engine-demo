package ont;

/** 打到标准输出，方便对照每种结果。 */
public final class Log {
    private Log() {}

    public static void line(String message) {
        System.out.println(message);
    }

    public static String supplier(int id) {
        if (id == Config.SUPPLIER_JIA) {
            return "甲";
        }
        if (id == Config.SUPPLIER_YI) {
            return "乙";
        }
        if (id == Config.SUPPLIER_BING) {
            return "丙";
        }
        return Integer.toString(id);
    }

    public static String rate(Double value) {
        if (value == null) {
            return "没有记录";
        }
        return String.format("%.2f", value);
    }
}
