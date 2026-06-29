# 📚 故障诊断论文集 | Fault Diagnosis Papers

收录近两年故障诊断领域权威期刊论文的自动聚合网站，涵盖五大研究方向：

- 🤖 **基于深度学习的方法** — CNN / Transformer / LSTM / GNN / Autoencoder
- 🔄 **迁移学习与域适应** — Domain Adaptation / Domain Generalization
- 🔗 **联邦学习与隐私保护** — Federated Learning / Privacy-Preserving
- 🧠 **可解释性** — Explainable AI / XAI / SHAP / LIME
- 🏭 **应用与部署** — 边缘计算 / 模型压缩 / 知识蒸馏 / 数字孪生 / 嵌入式系统

数据每半月自动更新，来源为 [Semantic Scholar](https://www.semanticscholar.org/) 和 [arXiv](https://arxiv.org/)。

## 🚀 快速开始

### 本地预览

```bash
# 启动本地 HTTP 服务器
python -m http.server 8080

# 浏览器打开
# http://localhost:8080
```

> ⚠️ 直接用 `file://` 协议打开会导致 fetch 跨域失败，必须通过 HTTP 服务器访问。

### 本地拉取论文数据

```bash
# 安装依赖
pip install -r scripts/requirements.txt

# 运行拉取脚本（大约需要 2-3 分钟）
python scripts/fetch_papers.py --output data/papers.json

# 可选：使用 Semantic Scholar API Key 提升速率
export S2_API_KEY=your_key_here
python scripts/fetch_papers.py --output data/papers.json
```

## 📦 项目结构

```
FD_web/
├── .github/workflows/update-papers.yml   # GitHub Actions 定时任务
├── scripts/
│   ├── fetch_papers.py                   # 论文数据拉取脚本
│   └── requirements.txt
├── data/
│   └── papers.json                       # 论文数据（自动更新）
├── css/
│   └── style.css                         # 移动端优先的响应式样式
├── js/
│   └── app.js                            # 前端逻辑
├── index.html                            # 入口页面
└── README.md
```

## 🔄 自动更新机制

- **频率**：每月 1 日和 15 日 UTC 08:00 自动执行
- **数据源**：Semantic Scholar API（主力）+ arXiv API（补充）
- **时间范围**：仅收录最近 2 年论文
- **去重**：DOI → Semantic Scholar paperId → 标准化标题哈希，三级去重
- **部署**：GitHub Pages 自动托管，推送即更新

也可以在 GitHub Actions 页面手动触发 `Update Papers Data` workflow。

## 🛠 技术栈

- **前端**：纯 HTML + CSS + JavaScript（无框架）
- **后端脚本**：Python 3 + requests
- **自动化**：GitHub Actions
- **托管**：GitHub Pages

## 📄 License

MIT
