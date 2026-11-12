package ont;

import java.util.UUID;

/** 确认更换不接收调用方传入的供应商编号。 */
public final class Engine {
    private final Portal portal;
    private final EditBus edits;

    public Engine(Portal portal, EditBus edits) {
        this.portal = portal;
        this.edits = edits;
    }

    public String confirm(int changeId, String actor) {
        ChangeRow row = PurchaseDb.load(changeId);
        Log.line(confirmHead(row, actor));
        String rejected = gate(row, actor);
        if (rejected != null) {
            return rejected;
        }
        try {
            writeBoth(row, actor);
        } catch (Reject ex) {
            PurchaseDb.audit(changeId, actor, "拒绝", "状态不允许");
            Log.line("确认 更换单 " + changeId + "：状态在写入时已变，拒绝，两个库退回");
            return "拒绝";
        }
        edits.publish(row.poId(), row.newSupplierId(), "待通知");
        Log.line("确认 更换单 " + row.id() + "：两个库已提交，状态改为待通知，xid " + GlobalTx.lastXid());
        return "接受";
    }

    public String resend(int changeId, String actor) {
        ChangeRow row = PurchaseDb.load(changeId);
        if (!"待通知".equals(row.status())) {
            PurchaseDb.audit(changeId, actor, "拒绝", "没有待发出的通知");
            Log.line("重发 更换单 " + changeId + "：状态是 " + row.status() + "，拒绝");
            return "拒绝";
        }
        if (!portal.notify(changeId)) {
            PurchaseDb.audit(changeId, actor, "待重发", "通知失败，仍待通知");
            Log.line("重发 更换单 " + changeId + "：门户超时，状态保持待通知，两个库不写");
            return "待重发";
        }
        PurchaseDb.setStatus(changeId, "已更换", actor, "已通知");
        edits.publish(row.poId(), row.newSupplierId(), "已更换");
        Log.line("重发 更换单 " + changeId + "：门户已送达，状态改为已更换，两个库不写");
        return "接受";
    }

    public String reconcile(int changeId, String actor) {
        ChangeRow row = PurchaseDb.load(changeId);
        if (!"待通知".equals(row.status())) {
            PurchaseDb.audit(changeId, actor, "拒绝", "没有待补记的通知");
            Log.line("补记 更换单 " + changeId + "：状态是 " + row.status() + "，拒绝");
            return "拒绝";
        }
        if (!portal.delivered(changeId)) {
            PurchaseDb.audit(changeId, actor, "拒绝", "门户没有送达记录");
            Log.line("补记 更换单 " + changeId + "：门户没有送达记录，拒绝");
            return "拒绝";
        }
        PurchaseDb.setStatus(changeId, "已更换", actor, "按门户补记");
        edits.publish(row.poId(), row.newSupplierId(), "已更换");
        Log.line("补记 更换单 " + changeId + "：按门户记录改成已更换，不再调用门户，两个库不写");
        return "接受";
    }

    private String gate(ChangeRow row, String actor) {
        if (!inFactoryIndex(row, actor)) {
            return "拒绝";
        }
        Double rate = DorisRate.of(row.newSupplierId());
        if (rate == null || rate >= Config.RATE_CUTOFF) {
            PurchaseDb.audit(row.id(), actor, "拒绝", "不在这次结果里");
            Log.line("确认 更换单 " + row.id() + "：准时率 " + Log.rate(rate) + "，拒绝，两个库不写");
            return "拒绝";
        }
        if (!Config.BUYER.equals(actor) && !Config.SUPERVISOR.equals(actor)) {
            PurchaseDb.audit(row.id(), actor, "拒绝", "不能做这个动作");
            Log.line("确认 更换单 " + row.id() + "：操作者 " + actor + " 不能做这个动作，拒绝");
            return "拒绝";
        }
        if (needsSupervisor(row, actor)) {
            PurchaseDb.setStatus(row.id(), "待主管确认", actor, "提交主管");
            Log.line("确认 更换单 " + row.id() + "：年采购额 " + row.annualAmount()
                    + " 超过 " + Config.ANNUAL_THRESHOLD + "，改为待主管确认，两个库不写");
            return "需要主管";
        }
        if (Config.BUYER.equals(actor) && !"待确认".equals(row.status())) {
            PurchaseDb.audit(row.id(), actor, "拒绝", "状态不允许");
            Log.line("确认 更换单 " + row.id() + "：采购员看到状态 " + row.status() + "，拒绝，两个库不写");
            return "拒绝";
        }
        if (Config.SUPERVISOR.equals(actor) && !"待主管确认".equals(row.status())) {
            PurchaseDb.audit(row.id(), actor, "拒绝", "状态不允许");
            Log.line("确认 更换单 " + row.id() + "：主管看到状态 " + row.status() + "，拒绝，两个库不写");
            return "拒绝";
        }
        Log.line("确认 更换单 " + row.id() + "：采购单在工厂 " + Config.FACTORY_ID
                + " 的索引里，准时率 " + Log.rate(rate) + "，进入全局事务");
        return null;
    }

    private static boolean inFactoryIndex(ChangeRow row, String actor) {
        try {
            if (OrderIndex.search(Config.FACTORY_ID).contains(row.poId())) {
                return true;
            }
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
        PurchaseDb.audit(row.id(), actor, "拒绝", "不在这次查找里");
        Log.line("确认 更换单 " + row.id() + "：采购单不在工厂 " + Config.FACTORY_ID + " 的索引里，拒绝");
        return false;
    }

    private static boolean needsSupervisor(ChangeRow row, String actor) {
        return Config.BUYER.equals(actor)
                && "待确认".equals(row.status())
                && row.annualAmount() > Config.ANNUAL_THRESHOLD;
    }

    private static void writeBoth(ChangeRow row, String actor) {
        GlobalTx.run(
                conn -> {
                    PurchaseDb.setSupplier(conn, row.id(), row.poId(), row.newSupplierId());
                    PurchaseDb.insertAudit(conn, row.id(), actor, "接受", "两库已换，通知未发");
                },
                conn -> ContractDb.setCounterparty(conn, row.poId(), row.newSupplierId()));
    }

    private static String confirmHead(ChangeRow row, String actor) {
        return "确认 更换单 " + row.id()
                + "，操作者 " + actor
                + "，当前状态 " + row.status()
                + "，新供应商 " + Log.supplier(row.newSupplierId())
                + "，年采购额 " + row.annualAmount();
    }

    public static String newEventId() {
        return UUID.randomUUID().toString().replace("-", "");
    }
}
