# PhyAgentOS Documentation

版本 / Version: **v0.1.6**
实现基线 / Implementation baseline: repository source at 2026-07-02

本目录由 PhyAgentOS 开发团队面向用户与生态开发者维护。

The PhyAgentOS development team maintains this directory as the public documentation for users and ecosystem developers. 

## 中文

1. [框架介绍](zh/01-framework-introduction.md)：架构、已实现能力、实现边界与后续设计
2. [用户手册](zh/02-user-manual.md)：安装、配置、Runtime 工作区、场景启动与排障
3. [开发者手册](zh/03-developer-manual.md)：核心接口、Schema、扩展流程、通信协议与测试
4. [Runtime 参数配置参考](zh/04-runtime-configuration-reference.md)：全局配置、Target、SkillRuntime、Session、Benchmark、Verification 与远程部署参数

补充手册：

- [运行手册](user_manual/README.md)：部署检查、Session 运维与故障分层
- [集成开发指南](user_development_guide/README.md)：Target/Skill/Policy/Perception 接入闭环
- [Unitree Go2 快速接入手册](user_development_guide/UNITREE_GO2_QUICK_START.md)：有线网络、SDK、TargetWS、真机安全启动与排障
- [通信架构](user_development_guide/COMMUNICATION.md)：消息、文件协议与 Runtime RPC 边界

## English

1. [Framework Introduction](en/01-framework-introduction.md): architecture, implemented capabilities, boundaries, and future design
2. [User Manual](en/02-user-manual.md): installation, configuration, runtime workspaces, scenario startup, and troubleshooting
3. [Developer Manual](en/03-developer-manual.md): core interfaces, schemas, extension workflows, protocols, and tests
4. [Runtime Configuration Reference](en/04-runtime-configuration-reference.md): global, Target, SkillRuntime, Session, benchmark, verification, and remote-host parameters

Supplementary manuals:

- [Operations Manual](user_manual/README_en.md): deployment checks, Session operations, and failure layers
- [Integration Development Guide](user_development_guide/README_en.md): Target/Skill/Policy/Perception integration loop
- [Unitree Go2 Quick Start Guide](user_development_guide/UNITREE_GO2_QUICK_START_en.md): wired networking, SDK, TargetWS, safe physical startup, and troubleshooting
- [Communication Architecture](user_development_guide/COMMUNICATION_en.md): messaging, file protocols, and Runtime RPC boundaries

## Architecture Diagrams / 架构图

- Agent Architecture: [中文](agent-architecture.html) · [English](agent-architecture.en.html)
- Benchmarking Architecture: [中文](benchmarking-architecture.html) · [English](benchmarking-architecture.en.html)
- SessionVerifier Architecture: [中文](session-verifier-architecture.html) · [English](session-verifier-architecture.en.html)
