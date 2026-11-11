package ont;

/** 动作拒绝写入。调用方看到的返回值仍是「拒绝」。 */
public final class Reject extends RuntimeException {
    public Reject(String message) {
        super(message);
    }
}
