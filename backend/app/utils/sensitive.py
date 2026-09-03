"""
安全防护（M6，方案安全清单㉑）：
- 敏感词过滤：内置演示词库（涉政/辱骂/广告），命中即拒绝
- prompt injection 检测：识别"忽略以上指令/越狱"等注入模式并拦截
- 输入清洗：去控制字符、归一化空白
"""
import re
import unicodedata

from app.core.exceptions import BizError

# 内置敏感词（毕设演示词库，生产可扩展为配置文件/第三方服务）
SENSITIVE_WORDS = {
    "违禁品", "代开发票", "刷单", "赌博", "毒品", "枪支",
    "办假证", "色情", "传销", "诈骗话术",
}

# prompt injection 常见模式（中英双语，忽略大小写；动词与目标词间允许少量修饰字）
_INJECTION_PATTERNS = [
    r"(忽略|忘掉|忘记|无视|绕过).{0,6}(指令|要求|规则|设定|限制)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|above)\s+",
    r"you\s+are\s+now\s+(a|an|in)\s+",
    r"扮演.{0,6}(越狱|jailbreak)",
    r"system\s*prompt",
    r"开发者模式",
    r"(忽略|修改)\s*<资料>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# 控制字符（保留 \n\t）
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_input(text: str) -> str:
    """输入清洗：去控制字符、压缩空白"""
    text = _CONTROL_RE.sub("", text)
    return re.sub(r"[ \t]{3,}", "  ", text).strip()


def check_sensitive(text: str) -> None:
    """
    敏感词与注入双重检查（命中抛 400，拒绝进入问答链路）。
    检查前做 NFKC 归一化，防止全角/异体字绕过。
    """
    normalized = unicodedata.normalize("NFKC", text).lower()
    # 1. 敏感词
    for word in SENSITIVE_WORDS:
        if word.lower() in normalized:
            raise BizError("提问包含违规内容，请文明提问", code="SENSITIVE_WORD", status_code=400)
    # 2. prompt injection
    if _INJECTION_RE.search(normalized):
        raise BizError("检测到异常指令输入，已被安全策略拦截", code="INJECTION_BLOCKED", status_code=400)
