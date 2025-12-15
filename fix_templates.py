# fix_templates.py
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def fix_template_structure():
    """اصلاح ساختار تمپلیت‌ها"""
    
    # 1. ایجاد پوشه‌ها
    home_templates_dir = BASE_DIR / 'templates' / 'home'
    registration_dir = home_templates_dir / 'registration'
    errors_dir = BASE_DIR / 'templates' / 'errors'
    
    home_templates_dir.mkdir(exist_ok=True, parents=True)
    registration_dir.mkdir(exist_ok=True, parents=True)
    errors_dir.mkdir(exist_ok=True, parents=True)
    
    print("📁 پوشه‌های تمپلیت ایجاد شدند")
    
    # 2. لیست فایل‌های تمپلیت
    template_files = [
        ('about.html', home_templates_dir),
        ('contact.html', home_templates_dir),
        ('index.html', home_templates_dir),
        ('project_detail.html', home_templates_dir),
        ('project_list.html', home_templates_dir),
        ('search.html', home_templates_dir),
        ('test.html', home_templates_dir),
        ('base.html', home_templates_dir),  # یا BASE_DIR / 'templates' اگر global است
    ]
    
    # 3. انتقال فایل‌ها
    for file_name, target_dir in template_files:
        source = BASE_DIR / 'templates' / file_name
        if source.exists():
            shutil.move(str(source), str(target_dir / file_name))
            print(f"📄 {file_name} → {target_dir.name}/")
    
    # 4. انتقال فایل‌های registration
    reg_source = BASE_DIR / 'templates' / 'registration'
    if reg_source.exists():
        for file in reg_source.iterdir():
            if file.is_file() and file.suffix == '.html':
                shutil.move(str(file), str(registration_dir / file.name))
                print(f"📄 registration/{file.name} → home/registration/")
    
    # 5. انتقال فایل‌های errors (اگر در جای دیگری هستند)
    errors_files = ['404.html', '500.html']
    for file_name in errors_files:
        source = BASE_DIR / file_name  # شاید در root باشند
        if source.exists():
            shutil.move(str(source), str(errors_dir / file_name))
            print(f"📄 {file_name} → errors/")
    
    print("✅ ساختار تمپلیت‌ها اصلاح شد")
    print("\nساختار جدید:")
    print("templates/")
    print("├── errors/")
    print("│   ├── 404.html")
    print("│   └── 500.html")
    print("└── home/")
    print("    ├── about.html")
    print("    ├── contact.html")
    print("    ├── index.html")
    print("    ├── project_detail.html")
    print("    ├── project_list.html")
    print("    ├── search.html")
    print("    ├── test.html")
    print("    ├── base.html")
    print("    └── registration/")
    print("        ├── login.html")
    print("        └── register.html")

if __name__ == '__main__':
    fix_template_structure()