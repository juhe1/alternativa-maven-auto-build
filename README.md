# Alternativa maven auto build
This script will map all maven projects inside directory determined in the MAVEN_PROJECTS_DIRECTORY constant. After mapping it will ask you for what you want to compile. After that it will automatically map all the dependencies and compile them if they are inside MAVEN_PROJECTS_DIRECTORY. If there is need for 3rd dependencies, the script will try to download them from repos that are in the MAVEN_REPOS constant list. 
## Setup
Following software is needed for the tool to work:
* jdk1.6.0_45: https://www.oracle.com/java/technologies/javase-java-archive-javase6-downloads.html
* maven 2.2.1: https://archive.apache.org/dist/maven/maven-2/2.2.1/binaries/
## How to use the tool
When the script is run, it will ask the group id, artifact id and version of the pom that you want to compile. Enter them and it should compile.
## How to compile projects.tanks.server:Runner:1.41.2.0 (Tanki Online 2010)
Some versions of build tools and configuration is missing from the leak (at least in the one that i have), so that's why some workarounds are needed.
Start by compiling platform.server.tools.pdp.maven:Plugin:1.4.5.0. This library must be compiled separately, because it is needed in platform.server.tools.pdp.maven:BasePom:1.0.0. When compiling Plugin, BasePom is needed. But wait, it isn't possible to use it because Plugin is not compiled yet. That's why Plugin must be comment out from the BasePom when the Plugin is compiled. It is also necessary to comment Plugin out from DONT_COMPILE constant list which can be found from the script. After compiling Plugin remember to uncomment Plugin from the BasePom and from the DONT_COMPILE list. 

There is also another library that must be compiled before compiling Runner. It is platform.server.tools.generator.maven:Flash:1.0.2.0. It should be straight forward to compile and should not need any workarounds.

Before Runner can be compiled, we need to setup Postgresql server. Postgresql 9.6 should be used. If you are on windows i highly recoment using WSL (Windows Subsystem for Linux) for seting up the database, because Postgresql doesn't host so old binarys for windows. Into the database you should setup user with name "platform" with password "buhf", database with name "platform" and schema named "model".

  After that, compiling projects.tanks.server:Runner:1.41.2.0 should be possible.
  Errors that you will get and how to solve them:
  * [WARNING] POM for 'platform.server.libraries.org:Hibernate:3.3.2.0:runtime' is invalid. Its dependencies (if any) will NOT be available to the current build.
	  * You can solve this by removing system path libraries from the Hibernate-3.3.2.0.pom that is located in ``LOCAL_REPOSITORY_DIRECTORY/platform/server/libraries/org/Hibernate/3.3.2.0/`` and ``your_home_dir/.m2/repository/platform/server/libraries/org/Hibernate/3.3.2.0``. Edit the .pom from both locations

WORK IN PROGRESS (the compilation guidea is not done there is missing details)
