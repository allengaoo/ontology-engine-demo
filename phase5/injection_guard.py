"""
Injection Guard：Prompt Injection防御

功能：
  1. 输入净化（移除疑似注入）
  2. 异常模式检测
  3. 安全事件记录
"""

from dataclasses import dataclass
from typing import List
import re


@dataclass
class SanitizationResult:
    """净化结果"""
    original: str
    sanitized: str
    threats_detected: List[str]
    risk_level: str  # "low", "medium", "high"


class InjectionGuard:
    """Prompt Injection防御"""
    
    # 危险关键词模式
    DANGEROUS_PATTERNS = [
        r"系统管理员[：:]",
        r"【.*指令.*】",
        r"debug\s*模式",
        r"忽略.*约束",
        r"覆盖.*规则",
        r"以上.*忽略",
        r"internal\s*instruction",
        r"override.*policy",
    ]
    
    def __init__(self):
        self.security_log = []
    
    def sanitize(self, user_input: str) -> SanitizationResult:
        """净化用户输入"""
        original = user_input
        sanitized = user_input
        threats = []
        
        # 规则1：移除危险关键词
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, sanitized, re.IGNORECASE):
                threats.append(f"检测到注入模式: {pattern}")
                sanitized = re.sub(pattern, "[已过滤]", sanitized, flags=re.IGNORECASE)
        
        # 规则2：移除过长输入
        if len(sanitized) > 500:
            threats.append("输入过长（>500字符）")
            sanitized = sanitized[:500] + "...[截断]"
        
        # 规则3：检测多重角色切换
        colon_count = sanitized.count("：") + sanitized.count(":")
        if colon_count > 3:
            threats.append(f"疑似多重角色（冒号数: {colon_count}）")
        
        # 规则4：检测多重分隔符
        separators = ["---", "###", "===", "***"]
        separator_count = sum(sanitized.count(sep) for sep in separators)
        if separator_count > 2:
            threats.append(f"疑似指令分隔符（数量: {separator_count}）")
        
        # 评估风险等级
        risk_level = self._assess_risk(threats)
        
        # 记录安全事件
        if threats:
            self._log_security_event(original, threats, risk_level)
        
        return SanitizationResult(
            original=original,
            sanitized=sanitized,
            threats_detected=threats,
            risk_level=risk_level
        )
    
    def _assess_risk(self, threats: List[str]) -> str:
        """评估风险等级"""
        if not threats:
            return "low"
        elif len(threats) == 1:
            return "medium"
        else:
            return "high"
    
    def _log_security_event(self, input_text: str, threats: List[str], risk_level: str):
        """记录安全事件"""
        event = {
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "input": input_text[:100] + "..." if len(input_text) > 100 else input_text,
            "threats": threats,
            "risk_level": risk_level
        }
        self.security_log.append(event)
        
        # 打印告警
        if risk_level == "high":
            print(f"\n⚠️  [SECURITY] 高风险注入检测: {len(threats)}个威胁")
            for threat in threats:
                print(f"    - {threat}")
    
    def get_security_log(self) -> List[dict]:
        """获取安全日志"""
        return self.security_log
