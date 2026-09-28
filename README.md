# 知乎双语日报

通过 Codex Skill 获取知乎热榜，按偏好筛选回答，生成英文精读与逐段中文翻译页面。支持增量缓存、本地预览和已配置的邮件连接器交付。

## 本地配置

1. 使用 Python 3 和 PowerShell；Python 脚本仅依赖标准库。
2. 将 `preferences.example.json` 复制为 `preferences.json`，再填写个人偏好。示例默认仅预览；邮件交付需设置 `recipient` 和 `delivery: "html_attachment"`，并连接邮件服务。
3. 当前脚本默认工作目录为 `F:/codexCoding/dailyZhihu`。其他目录需调整 `skills/zhihu-daily/scripts/run.ps1` 的 `$workspace`，或直接运行 Python 脚本并传入 `--workspace`。
4. `run.ps1` 从 `.private/zhihu-secret.dpapi` 读取当前 Windows 用户加密的知乎凭据；直接运行 Python 时使用环境变量 `ZHIHU_ACCESS_SECRET`。不要将凭据写入源码。
5. 按 `skills/zhihu-daily/SKILL.md` 完成抓取、编辑和构建流程。语言处理由调用 Skill 的 Codex 完成。

## 验证

```powershell
python -m unittest discover -s tests -v
```

## 隐私

`preferences.json`、`.private/`、`output/`、环境变量文件、密钥文件和 Python 缓存均不提交。仓库仅包含程序、测试、Skill 说明及脱敏配置示例。
