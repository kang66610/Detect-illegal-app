"""The 31 review points in the six categories of the 2019 identification method."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionItem:
    key: str
    category: int
    legal_basis: str
    title: str
    verification: str
    evidence_scope: str  # device, manual, server


_NAMES = {
    1: "未公开收集使用规则",
    2: "未明示收集使用个人信息的目的、方式和范围",
    3: "未经用户同意收集使用个人信息",
    4: "违反必要原则，收集与服务无关的个人信息",
    5: "未经同意向他人提供个人信息",
    6: "未按规定提供删除、更正功能或未公布投诉举报方式",
}


def category_name(category: int) -> str:
    return _NAMES[category]


def _items(article: int, category: int, titles: list[str], scopes: list[str]) -> list[RecognitionItem]:
    return [RecognitionItem(
        key=f"{article}.{index}", category=category,
        legal_basis=f"《App违法违规收集使用个人信息行为认定方法》第{['零','一','二','三','四','五','六'][article]}条第（{'一二三四五六七八九'[index - 1]}）点",
        title=title, verification={
            "device": "设备遍历与动态行为证据", "manual": "人工页面/流程核验", "server": "服务端审计记录与人工核验",
        }[scope], evidence_scope=scope,
    ) for index, (title, scope) in enumerate(zip(titles, scopes), start=1)]


RECOGNITION_ITEMS = (
    # ``manual`` used to mean “the old UI had no automation”.  These checks
    # now have deterministic Appium/LLM/Frida recipes.  The result remains
    # tri-state: an automated attempt without a complete evidence chain is
    # never treated as compliance.
    _items(1, 1, ["未公开收集使用规则", "首次运行未显著提示阅读规则", "规则入口访问超过 4 次点击", "规则内容难以阅读"], ["device", "device", "device", "device"])
    + _items(2, 2, ["未逐一明示收集使用个人信息的目的、方式和范围", "规则变更未适当通知用户", "申请权限时未同步告知目的", "规则内容晦涩难懂"], ["device", "server", "device", "device"])
    + _items(3, 3, ["同意前收集信息或开启权限", "拒绝后仍收集或频繁索要", "实际收集超出授权范围", "以默认勾选等非明示方式取得同意", "未同意即变更已设权限状态", "定向推送未提供非定向选项", "以欺骗误导方式诱导同意", "未提供撤回同意的途径", "违反已声明规则收集使用信息"], ["device", "device", "device", "device", "server", "device", "device", "device", "device"])
    + _items(4, 4, ["收集类型或权限与业务功能无关", "拒绝非必要信息后拒绝提供服务", "新增功能扩大收集范围并影响原功能", "收集频次超过实际需要", "以改善服务等理由强制同意", "一次性同意多个权限且不同意不能使用"], ["device", "device", "server", "device", "device", "device"])
    + _items(5, 5, ["未经同意且未匿名化向第三方提供信息", "App 后台向第三方提供收集的信息", "接入第三方应用时未经同意提供信息"], ["device", "server", "device"])
    + _items(6, 6, ["未提供有效更正、删除或注销功能", "删除、更正或注销设置不合理条件", "未及时响应相关请求", "客户端已操作但后台未完成", "未公布或未处理投诉举报"], ["device", "device", "server", "server", "device"])
)

ITEM_BY_KEY = {item.key: item for item in RECOGNITION_ITEMS}
