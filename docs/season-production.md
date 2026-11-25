# 五集生产与上下文边界

目标：在同一已知 Forest 局部影棚拍摄 **5 集 × 480 秒** 的胶囊人字幕预演。此文描述实现，不以文件存在或模型声称完成替代最终检查；运行结果在本机输出的 `season_report.json` 中。

## 角色与执行

1. `season.plan_series`：总编剧规划整季事实、初始知情者、证据依赖、五集场纲、每场时长和盒子归属目标。
2. `season.write_episodes`：逐集生成完整对白与动作意图；检查时长、事实公开与知情顺序、字幕阅读速度和无依据空等。失败反馈交回原编剧。
3. `season.direct_actions`：动作导演选择有明确时间的 move / face / take / put / give。每场继承上一场的真实物理末状态，数值编译失败交回原动作导演。
4. `season.direct_camera`：摄影指导决定切点、主体、焦距、构图占比、允许方位与静态/跟拍方式。接触动作不能被剪断或漏掉参与者/盒子。
5. `season.produce`：共享进程锁下执行 Blender。相机根据整个动作区间的保守主体包络求解有限候选，再对所有编码帧做实际姿态回读、碰撞和采样可见性检查。失败交回摄影指导，不移动人物掩盖问题。
6. `season.encode`：只使用实际 Blender 像素，按编剧时间添加字幕，完整编码/解码每集 11,520 帧。
7. `season.bake_all`：通过已有 camera harness SDK 导入整集镜头，保存可编辑 blend，回读整集实际角色、挂点、道具和相机动画。
8. `season.review` / `season.deliver`：按集检查实际对白与道具时序；验收 30 场和 4 次跨集边界，生成整季剧本、证据报告和本地审阅页面。

三类创作者通过共享包、版本化计划和执行反馈交流。当前不是完整原生 WorldOS 或完全自主三方协商系统；没有运行原生 camera harness finalize。

## 上下文怎样保持有限

| 使用者 | 加载 | 不逐步累积 |
|---|---|---|
| 编剧 | 固定角色与事实表、整季简要路线、本集场纲、精确知情台账、最近三场摘要 | 此前各集原始全文和所有执行日志 |
| 动作导演 | 本集剧本与动作意图、有限站位/路线、上一集物理末状态 | 全帧历史轨迹 |
| 摄影指导 | 本集对白、锁定动作操作、有限关键姿态 | 整季所有全帧数据 |
| 程序 | 完整数值数组、场景网格、所有事件与检查结果 | 无需模型上下文压缩 |

事实/知情、人物锚点与朝向、盒子归属属于可重放状态；摘要不是这些状态的权威来源。知识事件按对白时序更新，所有在场者都会听到普通对白。每个工单独立构造上下文，并记录输入签名、输入字符数、实际 token 用量与耗时。

当前动作和摄影仍以一集为模型工单边界、以场为执行边界。对于更长单集，可再缩小摄影工单；本轮没有把 40 分钟的全部细节放入一个摄影工单。

## 可恢复与缓存

- 已完成模型工单只有输入签名一致时才能复用；输入变化需要新修订 ID。
- 人物/盒子不能在场间或跨集重置，物理末状态必须逐场精确匹配。
- 每场摄影与像素有独立检查点；返修不重做未改动的已通过场次。
- 像素键包含源场景/渲染设定、所有人物可见变换、盒子位置与机位；没有把时间或字幕当作场景变化。只有完全相同的可见状态才复用。
- 字幕在渲染后按剧本独立合成。没有靠循环场次、倍速或延长空白凑八分钟。
- `affected_artifacts` 提供依赖闭包计算并有测试；本轮尚未完成“新改一个早期情节→整季自动修订重拍”的验证，不能把摄影局部返修当作该能力的证明。

## 运行

先完成 README 的本机配置，准备已有共享影棚包。下面的 `<output>` 是独立实验目录，`<prior-dir>` 包含先前实际测量的 `shared_studio.json` 和 `navigation_details.json`。

```bash
python -m season.plan_series --output <output> --prior <prior-dir>/shared_studio.json
python -m season.write_episodes --output <output>
python -m season.direct_actions --output <output> --prior-dir <prior-dir>
python -m season.direct_camera --output <output>
python -m season.review --output <output>
python -m season.produce --output <output> --prior-dir <prior-dir>
python -m season.bake_all --output <output> --prior-dir <prior-dir>
python -m season.verify_saved --output <output>
python -m season.contacts --output <output>
python -m season.deliver --output <output>
```

角色工单将本次合成剧本、结构化影棚信息与相应计划发送到配置的已认证 Codex 服务。场景、视频、日志、本机路径配置不提交 Git。主体是占位胶囊与不可见挂点，无人体动画、口型或真实抓握；没有音轨，没有 Seedance/Wan 成片。
