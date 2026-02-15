from config import WATERMARK_ENABLED
from datetime import datetime


def build_watermark_text(user, file_name):
    if not user:
        return ""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{user} | {file_name} | {stamp}"


def apply_watermark(config, user, file_name):
    try:
        customization = config.setdefault("editorConfig", {}).setdefault("customization", {})
        customization["forcesave"] = True
        if WATERMARK_ENABLED:
            text = build_watermark_text(user, file_name)
            customization["watermark"] = {"text": text}
    except Exception:
        pass
    return config


def inject_permissions(config, user, file_id, file_name=None):
    if file_name:
        config = apply_watermark(config, user, file_name)
    return config
