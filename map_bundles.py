from typing import List

import zipfile
import os

DIR:str = "C:\\Users\\juho\\Documents\\tankin_modaus\\romut\\alternativa_projects\\auto_build\\local_repository\\"

def is_osgi_bundle(jar_path:str):
	try:
		with zipfile.ZipFile(jar_path, "r") as jar:
			# Read the manifest file
			manifest = jar.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
			# Check for the OSGi bundle header
			return "Bundle-SymbolicName:" in manifest
	except Exception:
		# Skip jars without a proper manifest or if any error occurs
		return False

def find_bundle_jars(root_dir:str) -> List[str]:
	commands:List[str] = []
	for dirpath, _, filenames in os.walk(root_dir):
		for filename in filenames:
			if filename.lower().endswith(".jar"):
				jar_path = os.path.join(dirpath, filename)
				if is_osgi_bundle(jar_path):
					# Convert the path for the file URL scheme (adjust if needed)
					file_url:str = "file:" + jar_path.replace("\\", "/")
					command:str = f"install {file_url}"
					commands.append(command)
	return commands

if __name__ == "__main__":
	install_commands:List[str] = find_bundle_jars(DIR)
	for cmd in install_commands:
		print(cmd)
