# 平台需求清单（应用侧提出）

本文件只记录 `automation-app-dianping` 向底层提出的能力缺口。
实现发生在同级 `automation-kit` / `slidex` Codex 分支，不在本仓补底层。

## REQ-001 Appium 业务动作语义增强

## 背景
- 业务场景：点评 App 发布评价（搜索店铺 → 写评价 → 评分 → 上传照片 → 提交）
- 当前阻塞：通用 adapter 只有 `launch_app/tap/type_text/wait_for_element`，评分星级与相册选择只能靠 selector 约定硬拼

## 需要的公共能力
- 能力名 / 动作名：
  - `rate`（按维度/星级评分）
  - `pick_photos`（从设备相册或推送路径选择照片）
  - 可选 `submit_form` 成功判定约定
- 输入：dimension/value、photo paths、selector 策略
- 输出：标准 `ActionResult`，含是否命中 UI、已选数量
- 失败语义：元素缺失、超时、权限拒绝可区分

## 为什么不能在 app 内解决
- 若 app 自己封装 WebdriverIO/Appium 细节，会复制 adapter 生命周期与错误语义，破坏 L3/L4 边界

## 验收
- 离线测试应证明：fake session 可记录这些动作参数
- live 测试应证明：真机/模拟器可完成评分与照片选择
- 兼容约束：不破坏现有 `tap/type_text/wait_for_element`

## 应用侧过渡策略
- 已声明 `WorkflowStep.action("rate", ...)` 与 `pick_photos`
- 同时附带 `fallback_action` / `fallback_steps`（通用 tap），离线与未交付 adapter 可跑
- 平台交付后删除 fallback 字段即可，无需改业务门禁

## REQ-002 visual.challenge Android 截图结果契约固化

## 背景
- 业务场景：发布前/发布中识别图片验证码或界面文字
- 当前阻塞：app 只能请求 `visual.challenge`，结果字段与 retryable 语义仍依赖 provider 适配细节

## 需要的公共能力
- 能力名 / 动作名：`visual.challenge` / `solve`
- 输入：`android_screenshot_bytes`
- 输出：稳定 `CapabilityResult.data` 字段（text/action hints）与 `retryable`
- 失败语义：不可识别 / 可重试 / 需人工

## 为什么不能在 app 内解决
- app 不得导入 slidex 内部类型或脚本

## 验收
- 离线：fake executor 返回公共 `CapabilityResult`
- live：授权环境截图可求解
- 兼容：未安装 slidex 时 app 仍可 import 与离线测试

## REQ-003 正式包源 capability 矩阵

## 背景
- 业务场景：CI/发布不依赖 sibling path
- 当前阻塞：主线 automation-kit 发布包可能尚未含 capability 模块

## 需要的公共能力
- 已发布 `automation-kit>=0.3` wheel 包含 `automation_core.capabilities` 稳定导出

## 为什么不能在 app 内解决
- app 不能 vendoring 平台内核

## 验收
- 从正式包源安装后，本仓默认离线测试通过

## 应用侧过渡策略（CI）
- CI 通过 `sibling automation-kit main checkout` 有序回退到含 capability 的 kit 分支
- 主线/正式包源含 `automation_core.capabilities` 后，应清空该 env 并只装正式版本
- 回退失败时 CI 硬失败并指向 REQ-003，不再静默装无 capability 的 kit

## REQ-004 slidex android 截图滑块求解

## 背景
- 业务场景：真机发布流中途被风控滑块拦截（2026-09-20 实测触发）
- slidex `visual.challenge`/solve 已有 `slider_captcha` 与 `android_screenshot_bytes` 枚举与集成壳，但 `VisionContext.ANDROID_SCREENSHOT_BYTES` 在 `VisualChallengeSolver._solve_slider` 分派中落入 `unsupported_slider_context`

## 需要的公共能力
- slidex 提供纯图像求解路径：android 截图（bytes）→ 缺口左缘 x（`gap_x` / `distance_px`，截图像素），不依赖浏览器上下文
- 结果经 `CapabilityResult.data["metadata"]` 返回（`gap_x` / `distance_px`，`slidex.integrations.automation_kit` 透传）；app 侧 `live._build_slider_solver` 兼容旧 `gap_offset_px`（`_first("gap_x","distance_px")` 兜底）

## 为什么不能在 app 内解决
- 缺口识别是视觉能力，属 slidex provider 域；app 仓不实现视觉算法

## 验收
- `--enable-slidex` 下真实滑块触发时，dianping session 守卫完成「截图→求解→拖动→重试动作」闭环（dianping 侧管道已于 `e44078d` 就绪，含无 solver 的确定性失败路径）
- **2026-09-23 状态**：① slidex 侧 blocker 已关闭（`VisionContext.ANDROID_SCREENSHOT_BYTES` 并入 `_IMAGE_SLIDER_CONTEXTS` 纯图像分派，真实点评滑块截图实解 `gap_x=363`）；② app 侧桥接已接受 `gap_x`（绝对缺口 → 拖拽距离 = `(gap_x - 句柄_start_x) × distance_scale`）；③ **生产 uia2 路径补齐守卫**：`DianpingUia2Session` 此前无滑块守卫、`build_uia2_session_factory` 丢弃 `slider_solver`，导致 `--enable-slidex` 在 uia2（生产发布驱动）下空转 —— 已抽共享 `_slider_solution_params`/`_slider_drag_distance` 并给 uia2 会话接上守卫、工厂透传 solver。真机实测（OnePlus 7T / uia2）：求解器已挂上，真机 2.36MB 截图经 slidex 纯图像返回 `gap_x=445`；无滑块时 `SLIDER_DETECTED=False`、手柄未定位，不误触发。**尚待**：真实风控滑块出现时的「拖动→重试」闭环（需走进评价流程触发风控）

## 应用侧过渡策略
- 无 solver 或求解失败：动作确定性失败并留证（截图+page_source），提示人工处理
