# 可裁剪命令驱动运行时

基于 C++20 的独立应用内核，目标为静态组件、显式 Host 装配及统一受治理命令入口。首个正式支持环境为 Windows x64 / MSVC。

本仓库按 M0～M8 逐节点实施，首批检查点到 M3。**当前尚无可用运行时，不代表 Kernel 已冻结。** 只建设内核及其验证消费者，不扩展 CAD、CAM、机床、加工或 UI 模块。

M0 已完成：架构/证据门禁 3/3，固定参考版本 Release 回归 407/407，七场景三轮共 21 个独立进程初始基准已归档。下一节点为 M1 可裁剪骨架。参考结果不作为新运行时通过证明。

- [最终架构规划](Portable_Command_Runtime_Final_Architecture_v1.0.md)
- [执行计划与测试映射](docs/执行计划与测试映射.md)：唯一进度记录
- [独立内核 ADR](docs/ADR/0001-独立内核与固定参考版本.md)
- [来源与行为映射](docs/来源与行为映射.md)
- [M0 基线复现](docs/基线复现.md)
- [开发约束](AGENTS.md)

M0 门禁运行：

```powershell
cmake -S . -B build/m0
ctest --test-dir build/m0 -C Release --output-on-failure
```

原内核只作为固定版本参考，不是本工程的运行依赖；来源清单和实际测量证据随检查点提交。未运行项明确保留，不继承历史版本的测试绿灯。
