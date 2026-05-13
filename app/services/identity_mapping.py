import logging
from typing import Any, Dict

from app.models.user import User


logger = logging.getLogger("dingbridge.dingtalk")


def map_dingtalk_to_user(dingtalk_data: dict) -> User:
    """
    将钉钉用户信息映射到统一的 User 模型。
    """
    # 优先使用 unionId 作为唯一标识，其次是 userid
    subject = dingtalk_data.get("unionId") or dingtalk_data.get("userid") or "unknown"
    name = dingtalk_data.get("name") or "Unknown User"
    email = dingtalk_data.get("email")
    phone = dingtalk_data.get("mobile")

    # 处理部门信息：同时保留 部门名称 和 部门ID
    # dingtalk_adapter.fetch_normalized_user_info 返回了 dept_names 和 deptIds
    dept_names = dingtalk_data.get("dept_names") or []
    dept_ids = dingtalk_data.get("deptIds") or []
    
    # 将部门名称和 ID 混合放入 groups，或者采用特定格式如 "DeptName (DeptID)"
    # 这里简单起见，仅使用部门名称作为 groups，这是最通用的做法。
    # 如果下游系统（如 Coze）支持通过 groups 进行权限控制，通常匹配的是名称。
    groups = list(dept_names)
    
    # 也可以把 isAdmin 映射为一个特殊组
    if dingtalk_data.get("isAdmin"):
        groups.append("dingtalk_admin")

    user = User(
        subject=subject,
        name=name,
        email=email,
        phone_number=phone,
        groups=groups,
        raw=dingtalk_data,
    )
    logger.debug(
        "dingtalk_identity_mapping_result subject=%s has_name=%s has_email=%s has_phone=%s group_count=%s raw_has_userid=%s raw_has_unionid=%s",
        user.subject,
        bool(user.name),
        bool(user.email),
        bool(user.phone_number),
        len(user.groups),
        bool(dingtalk_data.get("userid") or dingtalk_data.get("userId")),
        bool(dingtalk_data.get("unionid") or dingtalk_data.get("unionId")),
    )
    return user


def user_to_oidc_claims(user: User) -> Dict[str, Any]:
    """
    将统一的 User 模型映射为 OIDC Claims。
    """
    claims: Dict[str, Any] = {}
    if user.name is not None:
        claims["name"] = user.name
    if user.email is not None:
        claims["email"] = user.email
    if user.phone_number is not None:
        claims["phone_number"] = user.phone_number
    if user.groups:
        claims["groups"] = list(user.groups)
    
    # 补充标准 OIDC Claims
    # preferred_username 通常映射为邮箱或工号/UnionId
    claims["preferred_username"] = user.name or user.subject
    
    # 如果 raw 中有部门 ID，也可以作为扩展 claim 暴露
    if user.raw:
        dept_ids = user.raw.get("deptIds")
        if dept_ids:
            claims["department_ids"] = dept_ids
            
    return claims
