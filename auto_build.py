from http.server import HTTPServer, SimpleHTTPRequestHandler
from packaging.version import InvalidVersion
from packaging import version
from datetime import datetime
from typing import Tuple
from typing import List
from typing import Dict

import xml.etree.ElementTree as ET
import subprocess
import threading
import requests
import hashlib
import shutil
import json
import glob
import stat
import os
import re

# When true, this script will run as repository server and will not compile anything
RUN_AS_REPOSITORY_SERVER = False

# Place where all the maven projects are located.
MAVEN_PROJECTS_DIRECTORY:str = ".\\alternativa_sources\\"

LOCAL_REPOSITORY_DIRECTORY:str = ".\\local_repository\\"

# Folder where POMs will be compied, when they are compiled.
COMPILATION_WORK_DIRECTORY:str = ".\\compilation_cache\\"

# The beging of groupId that identifies dependency as local. By local dependency i mean poms for which we have source code, and which can be compiled.
LOCAL_DEPENDENCY_IDENTIFIER_PREFIX:List[str] = [
	"platform",
	"projects.tanks"
]

# If dependency is not local and it does not exist in local repository try downloading it from these:
MAVEN_REPOS = [
	"https://repo.maven.apache.org/maven2/",
	"http://repo1.maven.org/maven2/",
	"https://nexus.griddynamics.net/nexus/content/repositories/public/",
	"https://repository.liferay.com/nexus/content/repositories/public/",
	"https://www.jabylon.org/maven/",
	"https://www.seasar.org/maven/maven2/",
	"http://maven.eparapher.com/repo/",
]

# These will not get compiled
DONT_COMPILE = [
	"platform.server.tools.pdp.maven:Plugin:1.4.5.0" # Will cause circular dependency
]

VERSION_OVERRIDE = {
	"org.eclipse.equinox.event:1.1.0-v20080225": "1.2.200",
	"org.eclipse.equinox.simpleconfigurator:1.0.0-v20080604": "1.0.200",
	"javax.xml.bind:2.0.0": "2.1.9",
	"org.eclipse.equinox.weaving.aspectj:1.0.0": "1.0.1",
	"org.eclipse.osgi:3.4.0-v20080605-1900": "3.5.0.v20090520",
	"org.eclipse.osgi:3.5.1": "3.5.2",
	"org.eclipse.osgi.services:3.2.0": "3.3.0",
	"org.eclipse.osgi.services:3.1.200-v20071203": "3.1.200-v20070605",
	"org.eclipse.equinox.registry:3.4.100": "3.5.400-v20140428-1507",
	"org.eclipse.equinox.cm:1.0.0-v20080509-1800": "1.0.300",
	"org.eclipse.equinox.log:1.1.0-v20080414": "1.2.300",
	"org.eclipse.equinox.metatype:1.0.0-v20070827": "1.1.0",
	"org.eclipse.equinox.registry:3.4.0-v20080516-0950": "3.5.301",
	"org.apache.commons.logging:1.0.4-v20080605-1930": "1.0.4",
	"com.adobe.flex.framework.flex-framework:4.0.0.4021": "4.1.0.15646",
	"org.eclipse.equinox.http.servlet:1.0.100-v20080427-0830": "1.1.200",
	"javax.servlet:2.4.0-v200806031604": "2.4",
	"org.eclipse.equinox.simpleconfigurator:1.0.101": "1.1.200",
	"platform.server.logger.Shared:1.0.1.3": "1.0.1.18",
	"platform.server.libraries.net.sf.Ehcache:1.0.4.1": "1.0.2",
	"projects.tanks.server.GarageBattleCommons:2.0.2.0": "2.0.3.0",
	"platform.server.libraries.org.quartz:1.0.0": "2.0.0",
	"projects.tanks.clients.fp10.TanksFonts:1.0.4.0": "1.0.6.0",
	"org.eclipse.equinox.http.jetty:1.1.0-v20080425": "1.1.0.v20080425",
	#"": "",
}

LIBRARY_OVERRIDE = {
	"platform.server.libraries.javax.Mail:0.0.0.1": "javax.mail.mail:1.4.3",
	#"": "",
}

REPOSITORY_SERVER_PORT = 8001

MAVEN_FLASH_GENERATOR = "platform.server.tools.generator.maven:Flash:1.0.2.0" 

maven_environment = os.environ.copy()  # Copy current environment variables
maven_environment["JAVA_HOME"] = "C:\\Users\\juho\\Documents\\sovellukset\\jdk1.6.0_45\\"
maven_environment["JAVA_TOOL_OPTIONS"] = "-Dfile.encoding=UTF8"
maven_environment["MVN_OPTS"] = ""

class Bcolors:
	HEADER = '\033[95m'
	OKBLUE = '\033[94m'
	OKCYAN = '\033[96m'
	OKGREEN = '\033[92m'
	WARNING = '\033[93m'
	FAIL = '\033[91m'
	ENDC = '\033[0m'
	BOLD = '\033[1m'
	UNDERLINE = '\033[4m'

def color_print(bcolor:str, text:str, end:str = "\n") -> None:
	print(bcolor + text + Bcolors.ENDC, end=end)

def download_file(url:str) -> None | bytes:
	try:
		response = requests.get(url)
		response.raise_for_status()  # Raise an exception for HTTP errors (e.g., 404)
		content = response.content
		return content
	except requests.exceptions.HTTPError as http_err:
		color_print(Bcolors.FAIL, f"HTTP error occurred: {http_err}")
	except requests.exceptions.RequestException as req_err:
		color_print(Bcolors.FAIL, f"Request error occurred: {req_err}")
	
	return None  # Return None if the download was unsuccessful

def download_file_from_3rd_repos(path) -> None | bytes:
	path_local = os.path.join(LOCAL_REPOSITORY_DIRECTORY, path)
	if os.path.exists(path_local):
		with open(path_local, "rb") as file:
			return file.read()
			
	for maven_repo_url in MAVEN_REPOS:
		file_data = download_file(maven_repo_url + path)
		if file_data is None or len(file_data) == 0:
			continue
		
		# cache file to disk
		os.makedirs(os.path.dirname(path_local), exist_ok=True)
		with open(path_local, "wb") as file:
			file.write(file_data)
			
		return file_data
	return

class RepositoryRequestHandler(SimpleHTTPRequestHandler):
	def extract_group_and_artifact(self, path:str) -> Tuple[str, str]:
		"""Extract groupId and artifactId from the folder path."""
		parts = path.strip("/").split("/")
		if len(parts) < 2:
			print("Invalid folder structure. Expected at least 'group/artifact' format.")
			return "", ""

		group_id = ".".join(parts[:-1])
		artifact_id = parts[-1]
		return group_id, artifact_id

	def extract_versions(self, dir:str) -> List[str]:
		"""Extract version numbers from subdirectories."""
		dir = os.path.join(LOCAL_REPOSITORY_DIRECTORY, dir)
		versions = []
		for subdir in os.listdir(dir):
			if glob.glob(os.path.join(dir, subdir) + "/*.pom"):
				versions.append(subdir)
		return sorted(versions, key=lambda v: list(map(int, v.split('.'))))

	def generate_maven_metadata(self, path:str) -> bytes:
		path_inside_local_repo:str = os.path.dirname(path)[1:]
		print("jddjdjd:", path_inside_local_repo)
		group_id, artifact_id = self.extract_group_and_artifact(path_inside_local_repo)
		versions = self.extract_versions(path_inside_local_repo)
		
		if not versions:
			print("No version folders found in the given directory.")
			return b""
		
		# Create XML structure
		metadata = ET.Element("metadata")
		ET.SubElement(metadata, "groupId").text = group_id
		ET.SubElement(metadata, "artifactId").text = artifact_id
		versioning = ET.SubElement(metadata, "versioning")
		versions_elem = ET.SubElement(versioning, "versions")
		
		for version in versions:
			ET.SubElement(versions_elem, "version").text = version
		
		ET.SubElement(versioning, "lastUpdated").text = datetime.utcnow().strftime("%Y%m%d%H%M%S")
		
		xml_bytes = ET.tostring(metadata, encoding="utf-8", xml_declaration=True)
		print("xml_bytes:", xml_bytes)
		return xml_bytes

	def do_GET(self):
		path = self.path
		print()
		print()
		color_print(Bcolors.OKGREEN, "MAVEN WANTS FILE: " + path)
		color_print(Bcolors.OKGREEN, "MAVEN WANTS FILE: ", end="")
		print(path)
		print()

		for dependency_str, dependency_override_str in LIBRARY_OVERRIDE.items():
			group_id_and_artifact_id_str, version = dependency_str.split(":")
			group_id = ".".join(group_id_and_artifact_id_str.split(".")[:-1])
			artifact_id = group_id_and_artifact_id_str.split(".")[-1]

			override_group_id_and_artifact_id_str, override_version = dependency_override_str.split(":")
			override_group_id = ".".join(override_group_id_and_artifact_id_str.split(".")[:-1])
			override_artifact_id = override_group_id_and_artifact_id_str.split(".")[-1]

			dependency_path = group_id.replace(".", "/") + "/" + artifact_id + "/" + version + "/" + artifact_id + "-" + version
			if dependency_path in path:
				new_dependency_path = override_group_id.replace(".", "/") + "/" + override_artifact_id + "/" + override_version + "/" + override_artifact_id + "-" + override_version
				path = path.replace(dependency_path, new_dependency_path)
				color_print(Bcolors.OKGREEN, f"OVERRIDING library from depency {dependency_str} to {dependency_override_str}")

		for dependency_str, override_version in VERSION_OVERRIDE.items():
			dependency_groupid_and_artifact, dependency_version = dependency_str.split(":")
			dependency_path = dependency_groupid_and_artifact.replace(".", "/") + "/" + dependency_version
			if dependency_path in path:
				path = path.replace(dependency_version, override_version)
				color_print(Bcolors.OKGREEN, f"OVERRIDING version from depency {dependency_str} to {override_version}")

		file_local_path:str = os.path.join(LOCAL_REPOSITORY_DIRECTORY, path.replace("/", "\\")[1:])
		print("file_local_path: ", file_local_path)
		if os.path.exists(file_local_path):
			# Open the file in binary mode
			with open(file_local_path, 'rb') as file:
				# Read all bytes from the file
				file_data = file.read()

				self.send_response(200)
				self.send_header("Content-type", "text/plain")
				self.send_header("Content-Length", str(len(file_data)))
				self.end_headers()
				self.wfile.write(file_data)
			return

		if os.path.basename(path) == "maven-metadata.xml" and os.path.exists(os.path.dirname(file_local_path)):
			file_data = self.generate_maven_metadata(path)

			if file_data == b"":
				self.send_response(404)
				self.end_headers()
				return

			self.send_response(200)
			self.send_header("Content-type", "text/plain")
			self.send_header("Content-Length", str(len(file_data)))
			self.end_headers()
			self.wfile.write(file_data)
			return
			
		for identifier in LOCAL_DEPENDENCY_IDENTIFIER_PREFIX:
			identifier = identifier.replace(".", "/")
			if path.startswith(identifier):
				self.send_response(404)
				self.end_headers()
				return

		file_data = download_file_from_3rd_repos(path)
		if not file_data is None:
			self.send_response(200)
			self.send_header("Content-type", "text/plain")
			self.send_header("Content-Length", str(len(file_data)))
			self.end_headers()
			self.wfile.write(file_data)
			return
			
		self.send_response(404)
		self.end_headers()


def create_pom_signature(group_id:str, artifact_id:str, version:str) -> str:
	return group_id + ":" + artifact_id + ":" + version

class PomInfo:
	def __init__(self, group_id:str, artifact_id:str, version:str, path:str, is_3rd:bool):
		self.group_id:str = group_id
		self.artifact_id:str = artifact_id
		self.version:str = version
		self.path:str = path
		self.is_3rd:bool = is_3rd
		self.dependencies:List = [] # List[PomInfo]
		self.signature:str = create_pom_signature(group_id, artifact_id, version)

	def __str__(self) -> str:
		return self.signature


class FileHashManager:

	IGNORE_SUB_FOLDERS = ["target\\", ".svn\\"]

	def __init__(self):
		self.hashes_by_directory:Dict[str, Dict[str, str]] = {}

	def _compute_hashes(self, directory:str) -> Dict[str, str]:
		"""
		Compute SHA-256 hashes for all files in a directory and its subdirectories.
		Returns a dictionary with relative file paths as keys and their hashes as values.
		"""

		print("computing hashes for ", directory)

		hashes = {}
		for root, dirs, files in os.walk(directory):
			if os.path.basename(root) in self.IGNORE_SUB_FOLDERS:
				continue

			for filename in files:
				file_path = os.path.join(root, filename)
				try:
					# Get relative path from the target directory
					rel_path = os.path.relpath(file_path, directory)
					
					# Compute file hash
					sha256 = hashlib.sha256()
					with open(file_path, "rb") as f:
						while True:
							chunk = f.read(4096)  # Read in 4KB chunks
							if not chunk:
								break
							sha256.update(chunk)

					hashes[rel_path] = sha256.hexdigest()
				except Exception as e:
					color_print(Bcolors.FAIL, f"Error processing {file_path}: {str(e)}")
		return hashes

	def _save_hashes(self, hashes:Dict[str, str], filename:str):
		"""Save hashes dictionary to a JSON file and to hashes_by_directory variable."""

		self.hashes_by_directory[filename] = hashes

		with open(filename, "w") as f:
			json.dump(hashes, f, indent=2)

	def _load_hashes(self, filename:str) -> Dict[str, str]:
		"""Load hashes from a JSON file"""

		if filename in self.hashes_by_directory:
			return self.hashes_by_directory[filename]

		if not os.path.exists(filename):
			return {}
		with open(filename, "r") as f:
			return json.load(f)

	def files_changed_in_directory(self, directory:str) -> bool:
		"""
		Check for changes in directory files compared to saved hashes.
		Returns a dictionary with changes and updates the hash file.
		"""

		hash_file_path = ".\\.hash_files\\" + directory.replace("\\", ".").replace("..", ".").replace(":", "") + ".json"

		# Load previous hashes
		old_hashes = self._load_hashes(hash_file_path)
		
		# Compute current hashes
		new_hashes = self._compute_hashes(directory)
		
		# Find changes
		has_changed:bool = False
		
		# Check for modified and added files
		for path in new_hashes:
			if path not in old_hashes:
				has_changed = True
			elif new_hashes[path] != old_hashes[path]:
				has_changed = True
		
		# Check for removed files
		for path in old_hashes:
			if path not in new_hashes:
				has_changed = True
		
		# Save current hashes as new baseline
		self._save_hashes(new_hashes, hash_file_path)
		
		return has_changed


file_hash_manager = FileHashManager()

def parse_xml_without_namespace(path:str) -> None | ET.Element:
	try:
		it = ET.iterparse(path)

		for _, el in it:
			# Strip namespace if it exists
			if '}' in el.tag:
				_, _, el.tag = el.tag.rpartition('}')  # Strip namespace
			# If no namespace, el.tag remains unchanged

		return it.root

	except ET.ParseError as e:
		color_print(Bcolors.FAIL, f"Failed to parse {path}: {e}")
		return

def read_element_text_raise_if_fail(element:None | ET.Element) -> str:
	if element is None:
		raise Exception("Element is None")
	if element.text is None:
		raise Exception("Element text is None")
	return element.text

def try_read_element_text(element:None | ET.Element) -> None | str:
	if element is None:
		return None
	if element.text is None:
		return None
	return element.text

def create_pom_info(group_id_:str, artifact_id_:str, version_:str, pom_dir_by_pom_signature:Dict[str, str]) -> PomInfo:
	# Use original version for finding the pom path
	pom_signature = create_pom_signature(group_id_, artifact_id_, version_)
	pom_path:str = ""
	if pom_signature in pom_dir_by_pom_signature:
		pom_path = pom_dir_by_pom_signature[pom_signature]

	return PomInfo(group_id_, artifact_id_, version_, pom_path, False)

def map_pom_dependencies(pom_info:PomInfo, pom_dir_by_pom_signature:Dict[str, str], pom_info_by_pom_signature:Dict[str, PomInfo] | None = None) -> Dict[str, PomInfo]:

	def is_3rd_dependecy(dependency:PomInfo) -> bool:
		for dependency_identifier in LOCAL_DEPENDENCY_IDENTIFIER_PREFIX:
			if dependency.group_id.startswith(dependency_identifier):
				return False
		return True

	def create_dependency_from_element(element:ET.Element) -> Tuple[str, str, str]:
		group_id:None | str = try_read_element_text(element.find("groupId"))
		artifact_id:None |str = try_read_element_text(element.find("artifactId"))
		version_:None |str = try_read_element_text(element.find("version"))

		dependency_group_id:str = ""
		dependency_artifact_id:str = ""
		dependency_version:str = ""

		if group_id is not None:
			group_id_clean:str = re.sub(r"\s+", "", group_id) # In some pom files there was spaces and other whitespace chars in groupId.
			dependency_group_id = group_id_clean
		if artifact_id is not None:
			artifact_id_clean:str = re.sub(r"\s+", "", artifact_id) # In some pom files there was spaces and other whitespace chars in artifactId.
			dependency_artifact_id = artifact_id_clean
		if version_ is not None:
			version_clean:str = version_.strip() # Strip whitespace chars from beginning and end of version.
			dependency_version = version_clean

		# Apply library override
		library_override_key = dependency_group_id + "." + dependency_artifact_id + ":" + dependency_version
		if library_override_key in LIBRARY_OVERRIDE:
			print("Overriding library for: " + library_override_key + " with: " + LIBRARY_OVERRIDE[library_override_key])
			override_group_id_and_artifact_id_str, override_version = LIBRARY_OVERRIDE[library_override_key].split(":")
			override_group_id = ".".join(override_group_id_and_artifact_id_str.split(".")[:-1])
			override_artifact_id = override_group_id_and_artifact_id_str.split(".")[-1]

			dependency_group_id = override_group_id
			dependency_artifact_id = override_artifact_id
			dependency_version = override_version

		# Apply version override
		version_override_key = dependency_group_id + "." + dependency_artifact_id + ":" + dependency_version
		if version_override_key in VERSION_OVERRIDE:
			print("Overriding version for: " + version_override_key + " with: " + VERSION_OVERRIDE[version_override_key])
			dependency_version = VERSION_OVERRIDE[version_override_key]

		# Check if version is this kind [1.0.0.0, 2.0.0.0)
		if len(dependency_version) > 1 and dependency_version[0] == "[" and dependency_version[-1] == ")":
				version_min_str, version_max_str = dependency_version[1:-1].split(",")
				version_min = version.parse(version_min_str.strip())
				version_max = version.parse(version_max_str.strip())

				# Find highest version in range
				highest_version = None
				for pom_signature in pom_dir_by_pom_signature.keys():
					group_i_id_str:str = pom_signature.split(":")[0]
					artifact_i_id_str:str = pom_signature.split(":")[1]
					version_i_str:str = pom_signature.split(":")[-1]

					if dependency_group_id != group_i_id_str or dependency_artifact_id != artifact_i_id_str:
						continue

					try:
						version_i = version.parse(version_i_str)
					except InvalidVersion:
						continue

					if version_min <= version_i <= version_max:
						if highest_version is None or version_i > highest_version:
							highest_version = version_i

				if highest_version is not None:
					dependency_version = str(highest_version)
				else:
					color_print(Bcolors.FAIL, "Could not find version in range: " + dependency_version)

		return (dependency_group_id, dependency_artifact_id, dependency_version)

	if pom_info_by_pom_signature is None:
		pom_info_by_pom_signature = {}

	stack:List[PomInfo] = [pom_info]

	while stack:
		current_pom_info:PomInfo = stack.pop()
		dependencies:List[Tuple[str, str, str]] = []

		pom_info_by_pom_signature[current_pom_info.signature] = current_pom_info
		
		print("Mapping dependencies for : " + current_pom_info.signature)

		if is_3rd_dependecy(current_pom_info):
			current_pom_info.is_3rd = True
			continue

		# ModelsBases are generated later so parsing their pom is not possible
		if current_pom_info.artifact_id.endswith("ModelsBase"):
			# Pom that will generate the ModelsBase.
			models_base_generator_group_id = current_pom_info.group_id.replace("client", "server")
			models_base_generator_artifact_id = current_pom_info.artifact_id[:-len("ModelsBase")]
			models_base_generator_pom_signature = models_base_generator_group_id + ":" + models_base_generator_artifact_id + ":" + current_pom_info.version

			dependency_pom_info = None
			if models_base_generator_pom_signature not in pom_info_by_pom_signature:
				# Map dependencies for every new dependency
				dependency_pom_info = create_pom_info(models_base_generator_group_id, models_base_generator_artifact_id, current_pom_info.version, pom_dir_by_pom_signature)
				stack.append(dependency_pom_info)
			else:
				dependency_pom_info = pom_info_by_pom_signature[models_base_generator_pom_signature]

			current_pom_info.dependencies.append(dependency_pom_info)

		if not current_pom_info.signature in pom_dir_by_pom_signature:
			color_print(Bcolors.FAIL, "Cannot map dependencies. POM folder path does not exist: " + current_pom_info.signature)
			continue

		pom_folder_path:str = pom_dir_by_pom_signature[current_pom_info.signature]
		pom_file_path:str = os.path.join(pom_folder_path, "pom.xml")
		if not os.path.isfile(pom_file_path):
			color_print(Bcolors.FAIL, "Cannot map dependencies. POM file does not exist: " + pom_file_path)
			continue

		root = parse_xml_without_namespace(pom_file_path)
		if root is None:
			color_print(Bcolors.FAIL, "Cannot map dependencies. Cannot parse POM file xml: " + pom_file_path)
			continue

		# Find all dependencies from dependencies/dependency
		dependency_elements = root.findall("dependencies/dependency")
		dependencies += [create_dependency_from_element(e) for e in dependency_elements]

		# Find all dependencies from dependencyManagement/dependencies/dependency
		management_dependency_elements = root.findall("dependencyManagement/dependencies/dependency")
		dependencies += [create_dependency_from_element(e) for e in management_dependency_elements]

		# Add plugins as dependencies
		plugin_elements = root.findall(".//build/plugins/plugin")
		dependencies += [create_dependency_from_element(e) for e in plugin_elements]

		# Add extensions as dependencies
		extension_elements = root.findall(".//build/extensions/extension")
		dependencies += [create_dependency_from_element(e) for e in extension_elements]

		# Add parent as dependency
		parent_element = root.find("parent")
		if parent_element is not None:
			dependencies.append(create_dependency_from_element(parent_element))

		# In the pom file dependencies can be in root/dependencies or in root/dependencyManagement/dependencies.
		# Same dependencies can be in both places, but it's version number may be defined only in one place (or in both).
		# Thats why we need to remove duplicates, and save the one that has version number.
		# This code will also remove dependencies that don't have groupId or Version

		added_dependencies:List[Tuple[str, str, str]] = []

		for i_group_id, i_artifact_id, i_version in dependencies:
			resolved_version = i_version

			# If dependency doesn't have version, try finding version from duplicate
			if resolved_version == "":
				for i_group_id2, i_artifact_id2, i_version2 in dependencies:
					if i_group_id == i_group_id2 and i_artifact_id == i_artifact_id2:
						resolved_version = i_version2

			dependency = (i_group_id, i_artifact_id, resolved_version)

			# If dependency is duplicate, skip
			if dependency in added_dependencies:
				continue

			if i_group_id == "" or resolved_version == "":
				continue

			added_dependencies.append(dependency)

			pom_signature = create_pom_signature(i_group_id, i_artifact_id, resolved_version)
			dependency_pom_info = None

			if pom_signature not in pom_info_by_pom_signature:
				# Map dependencies for every new dependency
				dependency_pom_info = create_pom_info(i_group_id, i_artifact_id, resolved_version, pom_dir_by_pom_signature)
				stack.append(dependency_pom_info)
			else:
				dependency_pom_info = pom_info_by_pom_signature[pom_signature]

			current_pom_info.dependencies.append(dependency_pom_info)
	
	return pom_info_by_pom_signature

def map_pom_paths(path:str) -> Dict[str, str]:
	pom_dir_by_pom_signature:Dict[str, str] = {}

	for dirpath, dirnames, filenames in os.walk(path):
		if not "pom.xml" in filenames:
			continue

		# Prevent os.walk from entering subdirectories of the current dir
		dirnames.clear()

		print("Mapping POM: " + dirpath)

		pom_path:str = os.path.join(dirpath, "pom.xml")
		root = parse_xml_without_namespace(pom_path)
		if root is None:
			continue

		group_id:None | str = try_read_element_text(root.find("groupId"))
		artifact_id:None |str = try_read_element_text(root.find("artifactId"))
		version:None |str = try_read_element_text(root.find("version"))

		if group_id is None or artifact_id is None or version is None:
			color_print(Bcolors.FAIL, "POM is missing groupId, artifactId or version: " + pom_path)
			continue

		# Remove whitespace chars
		group_id_clean:str = re.sub(r"\s+", "", group_id)
		artifact_id_clean:str = re.sub(r"\s+", "", artifact_id)
		version_clean:str = version.strip()
		pom_signature:str = create_pom_signature(group_id_clean, artifact_id_clean, version_clean)

		if pom_signature in pom_dir_by_pom_signature:
			color_print(Bcolors.WARNING, "POM already exists: " + pom_signature)
			continue

		pom_dir_by_pom_signature[pom_signature] = dirpath

	return pom_dir_by_pom_signature

def remove_readonly(func, path, _):
	"""Clear the read-only flag and retry deletion."""
	os.chmod(path, stat.S_IWRITE)  # Grant write permission
	func(path)

def box_print(message:str):
	print_line = "* " + message + " *"
	print()
	color_print(Bcolors.OKGREEN, "*" * len(print_line))
	color_print(Bcolors.OKGREEN, "*" + " " * (len(print_line) - 2) + "*")
	color_print(Bcolors.OKGREEN, print_line)
	color_print(Bcolors.OKGREEN, "*" + " " * (len(print_line) - 2) + "*")
	color_print(Bcolors.OKGREEN, "*" * len(print_line))
	print()

def print_maven_output(result:subprocess.CompletedProcess):
	print()
	color_print(Bcolors.OKGREEN, "Maven output:")
	color_print(Bcolors.OKGREEN, "<maven_output>")
	print(result.stdout)
	color_print(Bcolors.OKGREEN, "</maven_output>")
	print()

# If directory has been already checked, checking it again is not necessary.
files_changed_in_directory_already_checked:List = []

def generate_models_base(pom_info:PomInfo, pom_info_by_pom_signature:Dict[str, PomInfo]) -> bool:
	"""
	Generate ModelsBase.
	Returns:
		bool: True if generation was successful, False if not.
	"""

	def map_models_base(generation_result_path:str, models_base_pom_signature:str, models_base_group_id:str, models_base_artifact_id:str):
		pom_dir_by_pom_signature = map_pom_paths(generation_result_path)

		if models_base_pom_signature not in pom_info_by_pom_signature:
			models_base_pom_info = create_pom_info(models_base_group_id, models_base_artifact_id, pom_info.version, pom_dir_by_pom_signature)
		else:
			models_base_pom_info = pom_info_by_pom_signature[models_base_pom_signature]

		models_base_pom_info.path = generation_result_path
		map_pom_dependencies(models_base_pom_info, pom_dir_by_pom_signature, pom_info_by_pom_signature)

	models_base_group_id:str = pom_info.group_id.replace(".server", ".client")
	models_base_artifact_id = pom_info.artifact_id + "ModelsBase"
	models_base_pom_signature = create_pom_signature(models_base_group_id, models_base_artifact_id, pom_info.version)
	group_id_as_path:str = "\\".join(pom_info.group_id.split("."))
	compilation_work_dir:str = os.path.join(COMPILATION_WORK_DIRECTORY, group_id_as_path + "\\" + pom_info.artifact_id + "\\" + pom_info.version + "\\")
	compilation_work_dir = os.path.join(os.getcwd(), compilation_work_dir)
	generation_result_path:str = os.path.join(compilation_work_dir, "target\\client\\fp10\\")
	print("generation_result_path: " + generation_result_path)

	# Check if ModelsBase is already generated
	if os.path.exists(generation_result_path):
		if pom_info.signature in files_changed_in_directory_already_checked: 
			map_models_base(generation_result_path, models_base_pom_signature, models_base_group_id, models_base_artifact_id)
			return True

		files_changed_in_directory_already_checked.append(pom_info.signature)
		if not file_hash_manager.files_changed_in_directory(pom_info.path):
			map_models_base(generation_result_path, models_base_pom_signature, models_base_group_id, models_base_artifact_id)
			return True
	
	box_print("Generating ModelsBase for: " + pom_info.signature)

	result = subprocess.run(["mvn.bat", "-U", "install", MAVEN_FLASH_GENERATOR + ":generate"], cwd=compilation_work_dir, text=True, capture_output=True, env=maven_environment)

	print_maven_output(result)

	if result.returncode != 0:
		return False

	if not "[INFO] BUILD SUCCESSFUL" in result.stdout:
		color_print(Bcolors.FAIL, "ModelsBase generation failed: " + models_base_pom_signature)
		return False

	if not os.path.exists(generation_result_path):
		color_print(Bcolors.FAIL, "ModelsBase generation failed: " + models_base_pom_signature)
		return False

	color_print(Bcolors.OKGREEN, "ModelsBase generated successfully: " + models_base_pom_signature)

	map_models_base(generation_result_path, models_base_pom_signature, models_base_group_id, models_base_artifact_id)
	return True

def compile_pom(pom_info:PomInfo) -> bool:
	"""
	Compiles pom. It will not compile the pom again, if it was compiled before and no source code has changed since then. Adds the compiled pom to REPOSITORY_FOLDER_PATH.
	Returns:
		bool: True if compilation was successful, False if not.
	"""

	def compilation_needed(pom_info:PomInfo) -> bool:
		group_id_as_path:str = "\\".join(pom_info.group_id.split("."))
		repository_path_for_compilation_results = os.path.join(LOCAL_REPOSITORY_DIRECTORY, group_id_as_path + "\\" + pom_info.artifact_id + "\\" + pom_info.version + "\\")

		# Check if pom is already compiled
		if os.path.exists(os.path.join(repository_path_for_compilation_results, pom_info.artifact_id + "-" + pom_info.version + ".pom")):
			if pom_info.signature in files_changed_in_directory_already_checked: 
				return False

			files_changed_in_directory_already_checked.append(pom_info.signature)
			if not file_hash_manager.files_changed_in_directory(pom_info.path):
				return False
		
		return True

	if not compilation_needed(pom_info):
		return True

	# Compile the pom

	box_print("Compiling " + pom_info.signature)

	group_id_as_path:str = "\\".join(pom_info.group_id.split("."))
	compilation_work_dir = os.path.join(COMPILATION_WORK_DIRECTORY, group_id_as_path + "\\" + pom_info.artifact_id + "\\" + pom_info.version + "\\")
	compilation_work_dir = os.path.join(os.getcwd(), compilation_work_dir)

	if os.path.exists(compilation_work_dir):
		shutil.rmtree(compilation_work_dir, onerror=remove_readonly)

	# Copy the project into compilation_cache
	shutil.copytree(pom_info.path, compilation_work_dir)
	print("Copying project to " + compilation_work_dir + " from " + pom_info.path + " for compilation.")

	result = subprocess.run(["mvn.bat", "clean", "install", "-P release"], cwd=compilation_work_dir, text=True, capture_output=True, env=maven_environment)

	print_maven_output(result)

	if result.returncode != 0:
		return False

	if not "[INFO] BUILD SUCCESSFUL" in result.stdout:
		color_print(Bcolors.FAIL, "Compilation failed: " + pom_info.signature)
		return False

	repository_path_for_compilation_results = os.path.join(LOCAL_REPOSITORY_DIRECTORY, group_id_as_path + "\\" + pom_info.artifact_id + "\\" + pom_info.version + "\\")

	if not os.path.exists(repository_path_for_compilation_results):
		os.makedirs(repository_path_for_compilation_results)

	potential_compilation_result_file_paths = [
			os.path.join(compilation_work_dir, "target\\" + pom_info.artifact_id + "-" + pom_info.version + ".jar"),
			os.path.join(compilation_work_dir, "target\\release.swc"),
			os.path.join(compilation_work_dir, "target\\" + pom_info.artifact_id + "-" + pom_info.version + ".swc"),
	]

	compilation_result_file_path: None | str = None
	for potential_compilation_result_file_path in potential_compilation_result_file_paths:
		if os.path.exists(potential_compilation_result_file_path):
			compilation_result_file_path = potential_compilation_result_file_path
			break

	# If compilation didn't result any output files, we only copy pom to local repo.
	if compilation_result_file_path is None:
		shutil.copy(os.path.join(pom_info.path, "pom.xml"), os.path.join(repository_path_for_compilation_results, pom_info.artifact_id + "-" + pom_info.version + ".pom"))
		color_print(Bcolors.OKGREEN, "Compiled successfully: " + pom_info.signature)
		return True

	print("copying compilation result file to repository: " + compilation_result_file_path)
	compilation_result_file_extension:str = compilation_result_file_path.split(".")[-1]
	shutil.copy(compilation_result_file_path, os.path.join(repository_path_for_compilation_results, pom_info.artifact_id + "-" + pom_info.version + "." + compilation_result_file_extension))
	shutil.copy(os.path.join(pom_info.path, "pom.xml"), os.path.join(repository_path_for_compilation_results, pom_info.artifact_id + "-" + pom_info.version + ".pom"))

	color_print(Bcolors.OKGREEN, "Compiled successfully: " + pom_info.signature)
	return True
	
def compile_pom_and_its_dependencies(pom_info:PomInfo, pom_info_by_pom_signature:Dict[str, PomInfo]) -> bool:
	"""
	Compiles pom and its dependencys. Adds the compiled pom and compiled dependencies to REPOSITORY_FOLDER_PATH.
	Returns:
		bool: True if compilation was successful, False if not.
	"""

	stack:List[PomInfo] = [pom_info]
	missing_dependencies:List[PomInfo] = []
	resolved_dependencies:List[PomInfo] = []

	while stack:
		current_pom_info:PomInfo = stack.pop()
		#print("trying to compile: " + current_pom_info.signature)#, "dependencies:", [dependency.signature for dependency in current_pom_info.dependencies], "path:", current_pom_info.path)

		unsolvable_dependencies:bool = False
		dependencies_needing_compile:List[PomInfo] = []

		for dependency in current_pom_info.dependencies:
			if dependency in resolved_dependencies:
				continue

			if dependency in missing_dependencies:
				color_print(Bcolors.FAIL, "Can't compile " + current_pom_info.signature + " because dependency " + dependency.signature + " is missing.")
				unsolvable_dependencies = True
				continue

			print("Resolving dependency: " + dependency.signature)

			group_id_as_path:str = "/".join(dependency.group_id.split("."))
			dependency_local_repo_path:str = os.path.join(LOCAL_REPOSITORY_DIRECTORY, group_id_as_path + "\\" + dependency.artifact_id + "\\" + dependency.version + "\\")

			if dependency.is_3rd:
				if os.path.exists(dependency_local_repo_path):
					resolved_dependencies.append(dependency)
					continue

				dependency_pom_path:str = group_id_as_path + "\\" + dependency.artifact_id + "\\" + dependency.version + "\\" + "\\" + dependency.artifact_id + "-" + dependency.version + ".pom"
				dependency_pom_path = dependency_pom_path.replace("\\", "/")
				if download_file_from_3rd_repos(dependency_pom_path) is None:
					color_print(Bcolors.FAIL, "Missing 3rd dependency: " + dependency.group_id + ":" + dependency.artifact_id + ":" + dependency.version + " in: " + current_pom_info.signature)
					missing_dependencies.append(dependency)
					unsolvable_dependencies = True
					continue

				resolved_dependencies.append(dependency)
				continue

			# Try compiling dependency

			dont_compile_flag:bool = False

			# Set dont_compile_flag to true if dependency is in DONT_COMPILE list
			for dont_compile in DONT_COMPILE:
				dont_compile_group_id:str = dont_compile.split(":")[0]
				dont_compile_artifact_id:str = dont_compile.split(":")[1]
				dont_compile_version:str = dont_compile.split(":")[2]

				if dont_compile_group_id == dependency.group_id and dont_compile_artifact_id == dependency.artifact_id and dont_compile_version == dependency.version:
					color_print(Bcolors.OKGREEN, "Skipping dependency " + dependency.signature + " because it is in DONT_COMPILE list.")
					dont_compile_flag = True
					break

			if dont_compile_flag:
				continue

			dependencies_needing_compile.append(dependency)

		if unsolvable_dependencies:
			missing_dependencies.append(current_pom_info)
			stack += dependencies_needing_compile
			continue

		if dependencies_needing_compile:
			stack.append(current_pom_info)
			stack += dependencies_needing_compile
			continue

		if current_pom_info.path == "":
			group_id_as_path:str = "/".join(current_pom_info.group_id.split("."))
			dependency_local_repo_path:str = os.path.join(LOCAL_REPOSITORY_DIRECTORY, group_id_as_path + "\\" + current_pom_info.artifact_id + "\\" + current_pom_info.version + "\\")

			# If we don't have source codes, check that does the dependency exist inside local repo.
			if os.path.exists(dependency_local_repo_path):
				color_print(Bcolors.WARNING, "Can't compile pom " + current_pom_info.signature + " because source code is missing." + " Using one from local repo.")
				resolved_dependencies.append(current_pom_info)
				continue

			color_print(Bcolors.FAIL, "Can't compile pom " + current_pom_info.signature + " because its source code is missing.")
			missing_dependencies.append(current_pom_info)
			continue

		compilation_success:bool = compile_pom(current_pom_info)
		if not compilation_success:
			missing_dependencies.append(current_pom_info)
			continue

		group_id_as_path:str = "\\".join(current_pom_info.group_id.split("."))
		compilation_work_dir = os.path.join(COMPILATION_WORK_DIRECTORY, group_id_as_path + "\\" + current_pom_info.artifact_id + "\\" + current_pom_info.version + "\\")
		compilation_work_dir = os.path.join(os.getcwd(), compilation_work_dir)
		models_xml_file_path = os.path.join(compilation_work_dir, "target\\classes\\models.xml")

		# If models.xml exists, try generating ModelsBase.
		if os.path.exists(models_xml_file_path):
			generate_models_base(current_pom_info, pom_info_by_pom_signature)

		resolved_dependencies.append(current_pom_info)

	local_dependencies_resolved_count:int = len([dependency for dependency in resolved_dependencies if not dependency.is_3rd])
	local_dependencies_missing_count:int = len([dependency for dependency in missing_dependencies if not dependency.is_3rd])
	color_print(Bcolors.OKGREEN, "Total dependencies resolved: " + str(len(resolved_dependencies)) + ". Total dependencies missing: " + str(len(missing_dependencies)))
	color_print(Bcolors.OKGREEN, "Local dependencies resolved: " + str(local_dependencies_resolved_count) + ". Local dependencies missing: " + str(local_dependencies_missing_count))

	if pom_info.signature in missing_dependencies:
		return False

	return True

def start_repository_server():
	server_address = ("", REPOSITORY_SERVER_PORT)

	# Create and start the HTTP server with custom request handler
	httpd = HTTPServer(server_address, RepositoryRequestHandler)
	color_print(Bcolors.OKGREEN, "Server started at http://localhost:" + str(REPOSITORY_SERVER_PORT))
	httpd.serve_forever()

if RUN_AS_REPOSITORY_SERVER: 
	start_repository_server()
else:
	server_thread = threading.Thread(target=start_repository_server, daemon=True)
	server_thread.start()

	pom_dir_by_pom_signature:Dict[str, str] = map_pom_paths(MAVEN_PROJECTS_DIRECTORY)

	print("Please enter the information of the POM you want to compile:")
	pom_group_id:str = input("Group ID: ")
	pom_artifact_id:str = input("Artifact ID: ")
	pom_version:str = input("Version Number: ")

	pom_info:PomInfo = create_pom_info(pom_group_id, pom_artifact_id, pom_version, pom_dir_by_pom_signature)
	pom_info_by_pom_signature:Dict[str, PomInfo] = map_pom_dependencies(pom_info, pom_dir_by_pom_signature)
	compile_pom_and_its_dependencies(pom_info, pom_info_by_pom_signature)
