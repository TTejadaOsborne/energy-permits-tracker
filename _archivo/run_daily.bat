@echo off
SET PYTHONIOENCODING=utf-8
cd /d "C:\Users\tteja\Mars Renewable (Changxing) Co., Ltd\Spain Development - Documents\02_Market Information and Analysis\01_Portfolio Growth\03_Adverse Permits\00_Data\Nodalys"
python pipeline.py --ayer --boletines BOE BOCyL BOCM DOCM >> logs\daily.log 2>&1