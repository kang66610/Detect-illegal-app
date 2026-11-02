class PlatformError(Exception):
    """平台统一异常基类"""


class ApkValidationError(PlatformError):
    """APK 文件校验失败（非 APK/超限/损坏）"""


class ApkParseError(PlatformError):
    """APK 解析失败（加固/损坏等）"""


class TaskStateError(PlatformError):
    """任务状态流转非法"""


class RuleConfigError(PlatformError):
    """规则配置错误"""


class EngineUnavailableError(PlatformError):
    """真实检测引擎的可选依赖、设备或配置不可用。"""


class ExplorationError(PlatformError):
    """Appium 遍历过程无法继续。"""
