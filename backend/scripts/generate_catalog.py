"""
E-01 演示数据集生成器（固定种子，可复现）。

输出 sample_data/demo_catalog/：
- 商品参数表.csv    （72 个商品 × 9 字段，供 param 分块与商品目录构建）
- 商品详情文案.md   （每个商品一节，供 prose 分块做多跳/语义检索）
- 售后FAQ.md       （通用 + 品类售后问答，供 faq 分块）

用法：python scripts/generate_catalog.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "demo_catalog"
SEED = 42
rng = random.Random(SEED)

# (型号, 价格, 屏幕, 电池, 重量)
PHONES = [
    ("X5", 3999, "6.7英寸", "5000mAh", "198g"),
    ("X5 Pro", 5299, "6.8英寸", "5500mAh", "205g"),
    ("X6", 4299, "6.7英寸", "5100mAh", "196g"),
    ("X6 Pro", 5599, "6.8英寸", "5600mAh", "203g"),
    ("X7", 4799, "6.8英寸", "5200mAh", "199g"),
    ("X7 Pro", 6199, "6.9英寸", "5800mAh", "208g"),
    ("Note 12", 1999, "6.5英寸", "5000mAh", "186g"),
    ("Note 12 Pro", 2499, "6.6英寸", "5100mAh", "192g"),
    ("Fold S", 8999, "7.6英寸", "4800mAh", "263g"),
    ("Flip S", 5999, "6.9英寸", "4300mAh", "187g"),
    ("A3", 1299, "6.4英寸", "5000mAh", "178g"),
    ("A3 Pro", 1599, "6.5英寸", "5100mAh", "182g"),
]
EARPHONES = [
    ("风语者 TWS 无线耳机", 599, "45g"),
    ("风语者 Pro 降噪耳机", 1099, "52g"),
    ("风语者 Air", 399, "38g"),
    ("风语者 Air Pro", 699, "41g"),
    ("风语者 Studio", 899, "48g"),
    ("风语者 Studio Pro", 1299, "55g"),
    ("风语者 Lite", 199, "32g"),
    ("风语者 Lite Pro", 299, "35g"),
    ("风语者 Sport", 499, "40g"),
    ("风语者 Sport Pro", 799, "44g"),
    ("风语者 ANC 2", 899, "50g"),
    ("风语者 Max", 1599, "62g"),
]
LAPTOPS = [
    ("轻羽 14 笔记本电脑", 6499, "14英寸", "1.29kg"),
    ("轻羽 16 笔记本电脑", 8999, "16英寸", "1.8kg"),
    ("轻羽 14 Pro", 7999, "14英寸", "1.35kg"),
    ("轻羽 16 Pro", 10999, "16英寸", "1.92kg"),
    ("轻羽 Air 13", 5999, "13.3英寸", "1.08kg"),
    ("轻羽 Air 14", 6999, "14英寸", "1.15kg"),
    ("轻羽 Gaming 15", 9499, "15.6英寸", "2.35kg"),
    ("轻羽 Gaming 17", 12999, "17.3英寸", "2.8kg"),
    ("轻羽 Studio 15", 11499, "15.6英寸", "1.95kg"),
    ("轻羽 Studio 16", 13499, "16英寸", "2.05kg"),
    ("轻羽 Book 14", 4999, "14英寸", "1.32kg"),
    ("轻羽 Book 16", 5899, "16英寸", "1.72kg"),
]
WATCHES = [
    ("时界 Watch S", 1299, "1.43英寸", "14天"),
    ("时界 Watch S2", 1499, "1.43英寸", "16天"),
    ("时界 Watch Pro", 1999, "1.5英寸", "18天"),
    ("时界 Watch Pro 2", 2299, "1.5英寸", "20天"),
    ("时界 Fit", 599, "1.1英寸", "12天"),
    ("时界 Fit 2", 699, "1.2英寸", "14天"),
    ("时界 Kids", 799, "1.4英寸", "7天"),
    ("时界 Kids Pro", 999, "1.4英寸", "10天"),
    ("时界 Ultra", 2999, "1.5英寸", "21天"),
    ("时界 Ultra 2", 3499, "1.5英寸", "24天"),
    ("时界 Classic", 1699, "1.4英寸", "15天"),
    ("时界 Classic Pro", 1899, "1.4英寸", "17天"),
]
HOME = [
    ("护眼台灯 A1", 299, "-", "-", "1.1kg"),
    ("护眼台灯 A2", 399, "-", "-", "1.2kg"),
    ("护眼台灯 Pro", 599, "-", "-", "1.4kg"),
    ("智能摄像头 C1", 249, "-", "-", "180g"),
    ("智能摄像头 C2", 349, "-", "-", "210g"),
    ("智能摄像头 Pro", 499, "-", "-", "260g"),
    ("智能音箱 S1", 399, "-", "-", "320g"),
    ("智能音箱 S2", 599, "-", "-", "410g"),
    ("智能音箱 Pro", 899, "-", "-", "520g"),
    ("扫拖机器人 R1", 1599, "-", "-", "3.2kg"),
    ("扫拖机器人 R2", 2199, "-", "-", "3.4kg"),
    ("扫拖机器人 Pro", 2999, "-", "-", "3.8kg"),
]
TABLETS = [
    ("星河平板 T10", 2299, "10.6英寸", "7000mAh", "460g"),
    ("星河平板 T10 Pro", 2899, "11英寸", "7500mAh", "480g"),
    ("星河平板 T11", 2599, "11英寸", "7200mAh", "465g"),
    ("星河平板 T11 Pro", 3299, "11.5英寸", "7800mAh", "485g"),
    ("星河平板 T12", 2999, "12英寸", "8000mAh", "520g"),
    ("星河平板 T12 Pro", 3799, "12.4英寸", "8500mAh", "540g"),
    ("星河平板 Mini 8", 1599, "8.4英寸", "5100mAh", "290g"),
    ("星河平板 Mini 8 Pro", 1999, "8.4英寸", "5300mAh", "300g"),
    ("星河平板 Air 11", 3499, "11英寸", "7600mAh", "450g"),
    ("星河平板 Air 11 Pro", 4199, "11.2英寸", "7800mAh", "460g"),
    ("星河平板 Max 14", 4999, "14.2英寸", "9000mAh", "620g"),
    ("星河平板 Max 14 Pro", 5999, "14.2英寸", "9200mAh", "635g"),
]

COLORS = ["曜石黑", "冰川银", "晨曦金", "云雾白", "午夜黑", "月岩灰"]


def rows() -> list[dict]:
    items: list[dict] = []
    months = ["2025-01", "2025-03", "2025-04", "2025-06", "2025-08", "2025-09", "2025-11", "2026-01"]

    def add(brand, cat_rows, name_fmt=None):
        for i, entry in enumerate(cat_rows):
            name, price = entry[0], entry[1]
            if name_fmt:
                name = name_fmt.format(name)
            if len(entry) == 3:          # (name, price, weight)
                screen, batt, weight = "-", "-", entry[2]
            elif len(entry) == 4:        # (name, price, screen, weight)
                screen, batt, weight = entry[2], "-", entry[3]
            else:                        # (name, price, screen, battery, weight)
                screen, batt, weight = entry[2], entry[3], entry[4]
            if brand == "时界":
                weight = f"{42 + i * 2}g"
            items.append({
                "商品ID": f"P{len(items) + 1:03d}",
                "名称": name,
                "品牌": brand,
                "价格": str(price),
                "颜色": COLORS[i % len(COLORS)],
                "屏幕尺寸": screen,
                "电池容量": batt,
                "重量": weight,
                "上市时间": months[i % len(months)],
            })

    add("星河", PHONES, "星河 {} 智能手机")
    add("风语者", EARPHONES)
    add("轻羽", LAPTOPS)
    # 手表为 (name, price, screen, battery)，补一列重量后统一成 5 元组
    add("时界", [(n, p, s, b, "-") for n, p, s, b in WATCHES])
    add("明眸", HOME)
    add("星河", TABLETS)
    return items


def detail_sections(items: list[dict]) -> str:
    parts = ["# 商品详情文案（演示数据集）\n"]
    for item in items:
        name = item["名称"]
        if "手机" in name:
            scene = "日常通勤、影音娱乐与移动办公"
            extra = "支持 5G 双卡双待、NFC 门禁模拟与 IP68 级防尘防水。"
        elif "耳机" in name:
            scene = "通勤降噪、运动健身与线上会议"
            extra = "支持蓝牙 5.4 双设备连接，单次续航 8 小时，配合充电盒可达 32 小时。"
        elif "笔记本" in name:
            scene = "移动办公、编程开发与轻度创作"
            extra = "配备全功能 USB-C、HDMI 与雷电接口，支持 100W PD 快充。"
        elif "Watch" in name or "Fit" in name or "Kids" in name or "Ultra" in name or "Classic" in name:
            scene = "运动记录、健康监测与消息提醒"
            extra = "支持心率、血氧、睡眠与压力监测，5ATM 防水，可游泳佩戴。"
        elif "平板" in name:
            scene = "网课学习、轻办公与手写笔记"
            extra = "支持磁吸手写笔与键盘保护套，内置学习空间与家长管控。"
        else:
            scene = "家庭日常使用与智能联动"
            extra = "支持 App 远程控制与语音助手联动，固件可在线升级。"
        parts.append(
            f"## {name}\n\n"
            f"{name} 是 {item['品牌']} 面向 {scene} 推出的产品，官方售价 {item['价格']} 元，"
            f"提供 {item['颜色']} 等配色。\n\n"
            f"核心参数：屏幕 {item['屏幕尺寸']}，电池 {item['电池容量']}，重量 {item['重量']}，"
            f"上市时间 {item['上市时间']}。{extra}\n\n"
            f"包装清单包含主机、说明书与保修卡；自签收之日起支持 7 天无理由退货，"
            f"整机保修 1 年。具体以商品页与售后政策为准。\n"
        )
    return "\n".join(parts)


FAQ = """# 售后服务常见问题（演示数据集）

Q：商品支持无理由退货吗？
A：支持。自签收之日起 7 天内，商品完好且不影响二次销售的，可申请无理由退货。生鲜、贴身衣物等特殊品类除外。

Q：退货的运费由谁承担？
A：7 天无理由退货由买家承担退货运费；若因质量问题退货，运费由商家承担。

Q：保修期是多久？
A：整机保修 1 年，电池保修 6 个月，充电器等配件保修 3 个月。保修期自签收之日起计算。

Q：如何申请售后？
A：在「我的订单」中找到对应订单，点击「申请售后」，选择售后类型并上传凭证，客服将在 24 小时内审核。

Q：换货需要多久？
A：商家收到退回商品并检验无误后，2 个工作日内发出换货商品，偏远地区顺延 1~2 天。

Q：发票怎么开具？
A：下单时可填写发票信息，支持电子普通发票，订单完成后 48 小时内发送至预留邮箱。

Q：手机屏幕摔碎可以保修吗？
A：屏幕碎裂属于人为损坏，不在免费保修范围内，可付费维修；购买碎屏险的用户可按保险条款申请理赔。

Q：耳机防水吗？可以戴着洗澡吗？
A：风语者系列耳机支持 IPX4 级生活防水，可防汗防泼溅，但不建议佩戴洗澡或游泳。

Q：耳机如何配对？
A：打开充电盒盖并长按盒内按键 3 秒，指示灯闪烁后在手机蓝牙列表中搜索「风语者」并连接。

Q：笔记本电池如何保养？
A：建议开启电池保护模式，长期插电使用时将充电上限设为 80%，避免高温环境与深度放电。

Q：笔记本可以加内存吗？
A：轻羽 Book 与 Gaming 系列支持自行加装内存；Air 与 Studio 系列为板载内存，不支持扩容。

Q：手表可以游泳佩戴吗？
A：时界系列支持 5ATM 防水，可用于泳池游泳；不建议在热水浴、桑拿或潜水场景佩戴。

Q：手表续航突然变短怎么办？
A：请检查是否开启常亮屏与高频 GPS 定位，升级到最新固件；若仍异常可申请检测。

Q：平板支持手写笔吗？
A：星河平板 T 系列、Air 系列与 Max 系列支持磁吸手写笔，Mini 系列需单独购买专用笔。

Q：智能家居设备如何联网？
A：下载官方 App，设备通电后进入配网模式，按提示连接 2.4GHz Wi-Fi；暂不支持 5GHz 频段。

Q：扫地机器人需要定期维护吗？
A：建议每周清理尘盒与滚刷，每月擦拭传感器；耗材（滤网、边刷）建议每 3~6 个月更换。

Q：订单可以修改收货地址吗？
A：待发货状态可联系客服修改地址；已发货订单需联系快递拦截，可能产生额外费用。

Q：支持货到付款吗？
A：目前仅支持在线支付，暂不支持货到付款。

Q：可以开增值税专用发票吗？
A：支持。企业用户可在下单后联系客服提供开票资料，审核通过后 3 个工作日内开具。

Q：价保政策是怎样的？
A：自签收之日起 15 天内，若同一商品官方售价下调，可申请差价补偿，每个订单限一次。
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = rows()
    with (OUT_DIR / "商品参数表.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["商品ID", "名称", "品牌", "价格", "颜色", "屏幕尺寸", "电池容量", "重量", "上市时间"],
        )
        writer.writeheader()
        writer.writerows(items)
    (OUT_DIR / "商品详情文案.md").write_text(detail_sections(items), encoding="utf-8")
    (OUT_DIR / "售后FAQ.md").write_text(FAQ, encoding="utf-8")
    print(f"generated {len(items)} products -> {OUT_DIR}")


if __name__ == "__main__":
    main()
