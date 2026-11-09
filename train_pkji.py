"""Fine-tune YOLO11 untuk kelas PKJI. Siapkan dataset.yaml dengan names: [SM, MP, KS, LB, LT] (nama lama KB, BB tetap dikenali)."""
from ultralytics import YOLO
if __name__ == "__main__":
    m = YOLO("yolo11n.pt")
    m.train(data="dataset.yaml", epochs=100, imgsz=960, batch=16, project="runs", name="pkji")
    # salin runs/pkji/weights/best.pt -> yolo11_pkji.pt
