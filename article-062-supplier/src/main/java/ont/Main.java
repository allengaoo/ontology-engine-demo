package ont;

import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;

public final class Main {
    public static void main(String[] args) throws Exception {
        System.setProperty("file.listener.enabled", "false");
        Databases.openPlain();
        SchemaInit.apply();
        DorisRate.waitUntilAlive();
        DorisRate.resetTables();
        OrderIndex.recreate();
        EditBus.recreateTopic();
        GlobalTx.init();
        Databases.openXa();
        Seed.run();
        Portal portal = new Portal(Path.of("var", "portal.sqlite"));
        EditBus edits = new EditBus();
        Catchup catchup = new Catchup();
        Thread worker = new Thread(catchup, "catchup");
        worker.setDaemon(true);
        worker.start();
        catchup.awaitReady();
        Engine engine = new Engine(portal, edits);
        run(engine, portal, catchup);
        catchup.close();
        worker.join(5_000);
        edits.close();
        GlobalTx.shutdown();
        System.out.println("全部断言通过");
        System.exit(0);
    }

    private static void run(Engine engine, Portal portal, Catchup catchup) throws Exception {
        scene("两个库都准备好，提交前失败");
        Checks.bothRollBack();
        scene("新供应商准时率不低于 90%");
        rejectHighRate(engine);
        scene("年采购额超过 100 万，采购员确认");
        buyerNeedsSupervisor(engine);
        scene("主管确认，追平先暂停");
        supervisorWrites(engine, catchup);
        scene("待通知上再次确认");
        rejectSecondConfirm(engine);
        scene("通知超时，然后重发");
        notifyThenResend(engine, portal, catchup);
        scene("年采购额 10 万，门户已送达后补记");
        reconcileUnderThreshold(engine, portal);
    }

    private static void scene(String title) {
        System.out.println();
        System.out.println("—— " + title);
    }

    private static void rejectHighRate(Engine engine) throws Exception {
        Seed.setNewSupplier(Config.CHANGE_MAIN, Config.SUPPLIER_BING);
        String result = engine.confirm(Config.CHANGE_MAIN, Config.BUYER);
        int[] row = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        Checks.require("1 准时率不低于 90% 被拒绝", "拒绝".equals(result) && row[0] == 1 && row[1] == 0,
                "结果 " + result + "，供应商 " + row[0] + "，写入 " + row[1]);
        Seed.setNewSupplier(Config.CHANGE_MAIN, Config.SUPPLIER_YI);
    }

    private static void buyerNeedsSupervisor(Engine engine) {
        String result = engine.confirm(Config.CHANGE_MAIN, Config.BUYER);
        int[] purchase = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        int[] contract = ContractDb.supplierAndWrites(Config.PO_MAIN);
        String status = PurchaseDb.load(Config.CHANGE_MAIN).status();
        Checks.require(
                "2 超额时采购员只提交主管",
                "需要主管".equals(result) && "待主管确认".equals(status)
                        && purchase[0] == 1 && contract[0] == 1 && purchase[1] == 0 && contract[1] == 0,
                "结果 " + result + "，状态 " + status);
    }

    private static void supervisorWrites(Engine engine, Catchup catchup) throws Exception {
        catchup.pause();
        String result = engine.confirm(Config.CHANGE_MAIN, Config.SUPERVISOR);
        int[] purchase = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        int[] contract = ContractDb.supplierAndWrites(Config.PO_MAIN);
        String status = PurchaseDb.load(Config.CHANGE_MAIN).status();
        Checks.require(
                "3 主管确认，两个库一起写成乙",
                "接受".equals(result) && "待通知".equals(status)
                        && purchase[0] == 2 && contract[0] == 2 && purchase[1] == 1 && contract[1] == 1,
                "采购 " + purchase[0] + "/" + purchase[1] + "，合同 " + contract[0] + "/" + contract[1]
                        + "，xid " + GlobalTx.lastXid());
        Thread.sleep(1500);
        OrderIndex.Doc stale = OrderIndex.get(Config.PO_MAIN);
        Checks.require("3 附 副本仍是旧供应商", stale.supplierId() == Config.SUPPLIER_JIA,
                "文档供应商 " + stale.supplierId());
    }

    private static void rejectSecondConfirm(Engine engine) {
        String again = engine.confirm(Config.CHANGE_MAIN, Config.BUYER);
        int[] row = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        Checks.require("4 再次确认被拒绝", "拒绝".equals(again) && row[1] == 1 && row[0] == 2,
                "结果 " + again + "，写入仍是 " + row[1]);
    }

    private static void notifyThenResend(Engine engine, Portal portal, Catchup catchup) throws Exception {
        portal.failNext();
        String failed = engine.resend(Config.CHANGE_MAIN, Config.BUYER);
        int[] row = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        Checks.require(
                "5 通知失败停在待通知",
                "待重发".equals(failed) && "待通知".equals(PurchaseDb.load(Config.CHANGE_MAIN).status())
                        && row[1] == 1 && row[0] == 2,
                "结果 " + failed + "，写入 " + row[1]);
        String resent = engine.resend(Config.CHANGE_MAIN, Config.BUYER);
        int[] purchase = PurchaseDb.supplierAndWrites(Config.PO_MAIN);
        int[] contract = ContractDb.supplierAndWrites(Config.PO_MAIN);
        Checks.require(
                "5 重发成功才变成已更换",
                "接受".equals(resent) && "已更换".equals(PurchaseDb.load(Config.CHANGE_MAIN).status())
                        && purchase[1] == 1 && contract[1] == 1 && portal.callCount(Config.CHANGE_MAIN) == 2,
                "结果 " + resent + "，采购写入 " + purchase[1] + "，合同写入 " + contract[1]);
        catchup.resume();
        OrderIndex.Doc followed = waitDocument(Config.PO_MAIN, Config.SUPPLIER_YI, "已更换");
        Checks.require("5 附 副本追上乙", followed.supplierId() == 2 && "已更换".equals(followed.status()),
                "文档 " + followed.supplierId() + "/" + followed.status());
        String replay = "{\"event_id\":\"replay-fixed\",\"po_id\":17,\"supplier_id\":2,\"status\":\"已更换\"}";
        boolean first = catchup.apply(replay);
        boolean second = catchup.apply(replay);
        OrderIndex.Doc again = OrderIndex.get(Config.PO_MAIN);
        Checks.require("追平同一条编辑两次", first && !second
                        && again.supplierId() == followed.supplierId() && again.status().equals(followed.status()),
                "第一次 " + first + "，第二次 " + second);
    }

    private static void reconcileUnderThreshold(Engine engine, Portal portal) {
        String under = engine.confirm(Config.CHANGE_RECONCILE, Config.BUYER);
        int calls = portal.callCount(Config.CHANGE_RECONCILE);
        portal.markDeliveredWithoutCall(Config.CHANGE_RECONCILE);
        String patched = engine.reconcile(Config.CHANGE_RECONCILE, Config.BUYER);
        int[] purchase = PurchaseDb.supplierAndWrites(Config.PO_RECONCILE);
        int[] contract = ContractDb.supplierAndWrites(Config.PO_RECONCILE);
        Checks.require(
                "6 门户已送达则只补记",
                "接受".equals(under) && "接受".equals(patched)
                        && "已更换".equals(PurchaseDb.load(Config.CHANGE_RECONCILE).status())
                        && purchase[1] == 1 && contract[1] == 1
                        && portal.callCount(Config.CHANGE_RECONCILE) == calls
                        && purchase[0] == Config.SUPPLIER_YI,
                "确认 " + under + "，补记 " + patched + "，通知次数 " + portal.callCount(Config.CHANGE_RECONCILE));
    }

    private static OrderIndex.Doc waitDocument(int poId, int supplierId, String status) throws Exception {
        Instant deadline = Instant.now().plus(Duration.ofSeconds(30));
        OrderIndex.Doc last = null;
        while (Instant.now().isBefore(deadline)) {
            last = OrderIndex.get(poId);
            if (last != null && last.supplierId() == supplierId && status.equals(last.status())) {
                return last;
            }
            Thread.sleep(500);
        }
        throw new IllegalStateException("副本没有追上采购单 " + poId + ": " + last);
    }
}
