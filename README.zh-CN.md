# KinderSort — 幼儿园学生照片整理工具

[English](README.md)

KinderSort 是一个离线桌面工具，面向幼儿园老师。它会扫描活动照片，识别学生人脸，并自动把照片复制到对应学生文件夹。

## 功能亮点

- 全离线运行（不需要上传云端）
- 仅使用 CPU 进行人脸识别（`face_recognition` + `dlib`）
- 简单易用的 `tkinter` 图形界面
- 合照会复制到所有匹配到的学生文件夹
- 未匹配照片会复制到 `_unmatched`
- 在输出目录生成详细日志 `kindersort_log.txt`

## 适用场景

- 老师需要快速整理大量学生活动照片
- 学校对隐私有要求，必须本地离线处理

## 输入目录要求

在程序中需要选择 3 个文件夹：

1. **Reference Photos（参考照片）**：每位学生一张清晰正脸照，文件名即学生姓名  
   示例：`Ali.jpg`、`Siti.png`、`Kumar.jpeg`
2. **Events Folder（活动照片目录）**：包含多个活动子文件夹  
   示例：`Sports_Day/`、`Concert/`、`Field_Trip/`
3. **Output Folder（输出目录）**：整理结果写入位置

## 输出结构示例

```text
Output/
  Ali/
    Sports_Day__IMG_001.jpg
  Siti/
    Sports_Day__IMG_001.jpg
  _unmatched/
    blurry_photo.jpg
  kindersort_log.txt
```

## 使用步骤（老师快速上手）

1. 从项目 **Releases** 页面下载 `KinderSort.exe`。
2. 双击运行 `KinderSort.exe`。
3. 依次选择三个目录（Reference / Events / Output）。
4. 点击 **Start Sorting**。
5. 查看完成摘要并打开输出目录确认结果。

## 关键行为说明

- 人脸匹配阈值为 `0.5`（偏严格，减少误匹配）。
- 程序是“复制”照片，不会移动原图。
- Events 根目录下直接放置的照片会被跳过；请放在活动子文件夹中。
- 参考照未检测到人脸时，会提示并跳过该学生。

## EXE 下载方式

请从以下地址获取 Windows 可执行文件：

- **Releases**：`https://github.com/lerlerchan/KinderSort/releases`

为保持仓库体积轻量，项目不会把 `.exe` 直接放入常规 Git 历史。

## 开发者本地运行（源码）

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

打包 Windows 可执行文件：

```bash
pyinstaller --onefile --windowed --name "KinderSort" main.py
```

## 技术栈

- Python 3.10+
- `face_recognition`
- `dlib`
- `Pillow`
- `numpy`
- `tkinter`
- `PyInstaller`
