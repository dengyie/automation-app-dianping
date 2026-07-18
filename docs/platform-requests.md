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
- 已发布 `automation-kit>=0.2` wheel 包含 `automation_core.capabilities` 稳定导出

## 为什么不能在 app 内解决
- app 不能 vendoring 平台内核

## 验收
- 从正式包源安装后，本仓默认离线测试通过
