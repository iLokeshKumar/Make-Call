import os
import pkgutil
import deepgram

def find_class_in_package(package, class_name):
    path = package.__path__
    prefix = package.__name__ + "."

    for module_info in pkgutil.walk_packages(path, prefix):
        try:
            module = __import__(module_info.name, fromlist=[""])
            if hasattr(module, class_name):
                print(f"Found {class_name} in {module_info.name}")
                return module_info.name
        except Exception:
            pass
    return None

find_class_in_package(deepgram, "LiveTranscriptionEvents")
find_class_in_package(deepgram, "LiveOptions")
