# 参与贡献

感谢你愿意改进电脑百宝箱。

## 提交问题

- 先搜索现有 Issues，避免重复。
- Bug 请附：Windows 版本、Python 版本、操作步骤、期望结果、实际结果、`data/app.log` 中相关片段。
- **不要上传真实个人文件、备份目录清单、密码或访问令牌**；示例路径请用 `C:\Demo\...`。

## 提交代码

1. Fork 本仓库；
2. 从 `main` 创建分支；
3. 保持“无第三方运行时依赖”，优先使用标准库和 tkinter；
4. 不提交 `data/`、`dist/`、`build/`、`__pycache__/`；
5. 补对应测试，并至少运行：

```bat
python tests\test_engine.py
python tests\test_ui_smoke.py
python tests\test_tray_menu.py
```

6. 在 Pull Request 中说明改动原因、影响范围和测试结果。

## 代码风格

- Python 3.10+；
- 尽量保持现有模块划分和中文 UI 文案风格；
- 涉及删除、覆盖、关机等破坏性操作时，必须提供确认或可取消路径；
- 发现安全问题时不要公开提交利用细节，请先联系维护者。
