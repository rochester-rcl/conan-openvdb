import os
import shutil
from conans import ConanFile, CMake, tools
from macholib import mach_o, MachO
import subprocess


class OpenVDBConan(ConanFile):
    name = "OpenVDB"
    version = "7.0.0"
    license = "MPL-2.0"
    description = "OpenVDB is an open source C++ library comprising a novel hierarchical data structure and a large suite of tools for the efficient storage and manipulation of sparse volumetric data discretized on three-dimensional grids."
    requires = (
        "boost/1.69.0@conan/stable",
        "glfw/3.3@bincrafters/stable",
        "tbb/2020.1",
        "Blosc/1.5.0@rcldsl/stable",
        "zlib/1.2.11@conan/stable",
        "IlmBase/2.4.0@rcldsl/stable",
        "OpenEXR/2.4.0@rcldsl/stable",
    )
    url = "https://github.com/rochester-rcl/conan-openvdb"
    boost_components_needed = "iostreams", "system", "thread"
    generators = "cmake"
    settings = "os", "arch", "compiler", "build_type"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = "shared=False", "fPIC=False", "Boost:fPIC=True"
    exports = ["CMakeLists.txt"]
    build_policy = "missing"
    keep_imports = True

    def config_options(self):
        if self.settings.os == "Windows":
            self.options.remove("fPIC")

    def configure(self):
        if self.options.shared and "fPIC" in self.options.fields:
            self.options.fPIC = True
            # Set fPIC=True to all dependencies that have the option.
            for _, pkg_opts in self.options.deps_package_values.items():
                if "fPIC" in pkg_opts.fields:
                    pkg_opts.fPIC = True

        # Exclude Boost components which are not needed.
        boost_options = self.options["boost"]
        for boost_option in boost_options.fields:
            if not boost_option.startswith("without_"):
                continue
            component = boost_option[8:]
            if component not in self.boost_components_needed:
                boost_options.add_option(boost_option, True)

        # Intel-TBB does not support static linking in Windows
        if self.settings.os == "Windows":
            self.options["tbb"].shared = True

    def source(self):
        tools.download(
            "https://github.com/AcademySoftwareFoundation/openvdb/archive/v{}.tar.gz".format(
                self.version
            ),
            "openvdb.tar.gz",
        )
        tools.untargz("openvdb.tar.gz")
        os.unlink("openvdb.tar.gz")

        tools.replace_in_file(
            "{}/openvdb-{}/CMakeLists.txt".format(self.source_folder, self.version),
            "project(OpenVDB)",
            """project(OpenVDB)
               include(${CMAKE_BINARY_DIR}/conanbuildinfo.cmake)
               conan_basic_setup()
               ADD_DEFINITIONS(-std=c++11)
            """,
        )

    def imports(self):
        self.copy("*.dylib", src="lib", dst="lib", keep_path=False)
        self.copy("*.so", src="lib", dst="lib", keep_path=False)
        self.copy("*.dll", src="bin", dst="bin", keep_path=False)

    def change_tbb_rpath(self):
        tbb_files = set()
        for lib_path in self.deps_cpp_info["tbb"].lib_paths:
            for dirname, dirnames, files in os.walk(lib_path):
                for f in files:
                    if "libtbb" in f:
                        tbb_files.add(os.path.join(dirname, f))
        for f in tbb_files:
            basename = os.path.basename(f)
            cmd = ["install_name_tool", "-id", basename, f]
            subprocess.call(cmd)
            if "libtbbmalloc_proxy" in basename:
                cmd = [
                    "install_name_tool",
                    "-change",
                    "@rpath/libtbbmalloc.dylib",
                    "libtbbmalloc.dylib",
                    f,
                ]
                subprocess.call(cmd)

    def build(self):
        os.environ.update(
            {
                "BOOST_ROOT": self.deps_cpp_info["boost"].rootpath,
                "TBB_ROOT": self.deps_cpp_info["tbb"].rootpath,
                "BLOSC_ROOT": self.deps_cpp_info["Blosc"].rootpath,
                "ILMBASE_ROOT": self.deps_cpp_info["IlmBase"].rootpath,
                "OPENEXR_ROOT": self.deps_cpp_info["OpenEXR"].rootpath,
                "GLFW3_ROOT": self.deps_cpp_info["glfw"].rootpath,
            }
        )

        cmake = CMake(self)

        cmake.definitions.update(
            {
                "BUILD_SHARED": self.options.shared,
                "BUILD_TOOLS": False,
                "OPENVDB_BUILD_CORE": True,
                "OPENVDB_BUILD_BINARIES": False,
                "OPENVDB_BUILD_UNITTESTS": False,
                "OPENVDB_BUILD_PYTHON_MODULE": False,
                "OPENVDB_ENABLE_RPATH": False,
                "ILMBASE_LOCATION": self.deps_cpp_info["IlmBase"].rootpath,
                # "OPENVDB_ENABLE_3_ABI_COMPATIBLE": True,
                "ILMBASE_NAMESPACE_VERSIONING": True,
                "OPENEXR_NAMESPACE_VERSIONING": True,
                "CMAKE_INSTALL_PREFIX": self.package_folder,
                "USE_GLFW3": True,
                "GLFW3_USE_STATIC_LIBS": True,
            }
        )
        # fix tbb install name on osx
        if self.settings.os == "Macos":
            self.change_tbb_rpath()

        if "fPIC" in self.options.fields:
            cmake.definitions["CMAKE_POSITION_INDEPENDENT_CODE"] = self.options.fPIC

        cmake.configure(
            source_dir="{}/openvdb-{}".format(self.source_folder, self.version)
        )
        cmake.build(target="install")

    @staticmethod
    def list_linked_dependencies(library):
        def get_dependencies(library_path):
            m = MachO.MachO(library_path)
            deps = []
            for header in m.headers:
                for load_command, dylib_command, data in header.commands:
                    if load_command.cmd == mach_o.LC_LOAD_DYLIB:
                        dep = data.decode("ascii")
                        dep = dep.rstrip("\x00")
                        if "/" not in dep:
                            deps.append("{}/{}".format(os.path.dirname(library), dep))
            if len(deps) > 0:
                children = [get_dependencies(dep) for dep in deps]
                all_deps = deps + [dep for child in children for dep in child]
                return set(all_deps)
            else:
                return []

        return get_dependencies(library)

    def get_dependencies(self):
        library = "{}/lib/libopenvdb.dylib".format(self.build_folder)
        dependencies = self.list_linked_dependencies(library)
        return dependencies

    def package(self):
        dependencies = [os.path.basename(dep) for dep in self.get_dependencies()]
        for dependency in dependencies:
            self.copy(dependency, src="lib", dst="lib")
        # copy tbb dependencies as well
        self.copy("libtbb*", src="lib", dst="lib")
        self.copy(
            "LICENSE",
            src="{}/openvdb-{}".format(self.source_folder, self.version),
            dst="licenses",
        )
        self.copy("*.h", dst="include", src="package/include", keep_path=True)
        self.copy("*", dst="lib", src="package/lib", keep_path=False)
    
    def deploy(self):
        self.copy("*.dylib", dst="lib", keep_path=False)
        self.copy("*.so", dst="lib", keep_path=False)
        self.copy("*.a", dst="lib", keep_path=False)
        self.copy("*.dll", dst="src", keep_path=False)

    def package_info(self):
        self.cpp_info.cppflags.append("-std=c++11")

        if self.settings.os == "Windows" and not self.options.shared:
            self.cpp_info.libs = ["libopenvdb"]
        else:
            self.cpp_info.libs = ["openvdb"]

        self.cpp_info.defines = ["OPENVDB_USE_BLOSC"]

        if self.options.shared:
            self.cpp_info.defines.append("OPENVDB_DLL")
        else:
            self.cpp_info.defines.append("OPENVDB_STATICLIB")

        if not self.options["OpenEXR"].shared:
            self.cpp_info.defines.append("OPENVDB_OPENEXR_STATICLIB")
