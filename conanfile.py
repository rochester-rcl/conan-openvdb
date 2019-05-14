import os
import shutil
from conans import ConanFile, CMake, tools


class OpenVDBConan(ConanFile):
    name = "OpenVDB"
    version = "6.0.0"
    license = "MPL-2.0"
    description = "OpenVDB is an open source C++ library comprising a novel hierarchical data structure and a large suite of tools for the efficient storage and manipulation of sparse volumetric data discretized on three-dimensional grids."
    requires = ("boost/1.67.0@conan/stable",
                "glfw/3.3@bincrafters/stable",
                "TBB/2018_U6@conan/stable",
                "Blosc/1.5.0@jromphf/stable",
                "zlib/1.2.11@conan/stable",
                "IlmBase/2.3.0@jromphf/stable",
                "OpenEXR/2.3.0@jromphf/stable",
                )
    boost_components_needed = "iostreams", "system", "thread"
    generators = "cmake"
    settings = "os", "arch", "compiler", "build_type"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = "shared=False", "fPIC=False", "Boost:fPIC=True"
    exports = ["CMakeLists.txt"]
    build_policy = "missing"

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
            self.options["TBB"].shared = True

    def source(self):
        tools.download(
            "https://github.com/AcademySoftwareFoundation/openvdb/archive/v{}.tar.gz".format(self.version),
            "openvdb.tar.gz"
        )
        tools.untargz('openvdb.tar.gz')
        os.unlink('openvdb.tar.gz')

        tools.replace_in_file("{}/openvdb-{}/CMakeLists.txt".format(self.source_folder, self.version),
                              "PROJECT ( OpenVDB )",
                              "PROJECT ( OpenVDB )\n" +
                              "include(${CMAKE_BINARY_DIR}/conanbuildinfo.cmake)\n" +
                              "conan_basic_setup()\n" +
                              "ADD_DEFINITIONS(-std=c++11)")
        # Dont build vdb_view to avoid GLFW error
        shutil.copy("CMakeLists.txt".format(self.source_folder), "{}/openvdb-{}/openvdb/CMakeLists.txt".format(self.source_folder, self.version))
        shutil.copy("FindILMBase.cmake".format(self.source_folder), "{}/openvdb-{}/cmake/FindILMBase.cmake".format(self.source_folder, self.version))

    def build(self):
        os.environ.update(
            {"BOOST_ROOT": self.deps_cpp_info["boost"].rootpath,
             "TBB_ROOT": self.deps_cpp_info["TBB"].rootpath,
             "BLOSC_ROOT": self.deps_cpp_info["Blosc"].rootpath,
             "ILMBASE_ROOT": self.deps_cpp_info["IlmBase"].rootpath,
             "OPENEXR_ROOT": self.deps_cpp_info["OpenEXR"].rootpath,
             "GLFW3_ROOT": self.deps_cpp_info["glfw"].rootpath
             })

        cmake = CMake(self)

        cmake.definitions.update(
            {"BUILD_SHARED": self.options.shared,
             "BUILD_TOOLS": False,
             "OPENVDB_BUILD_CORE": True,
             "OPENVDB_BUILD_BINARIES": False,
             "OPENVDB_BUILD_UNITTESTS": False,
             "OPENVDB_BUILD_PYTHON_MODULE": False,
             "OPENVDB_ENABLE_3_ABI_COMPATIBLE": True,
             "ILMBASE_NAMESPACE_VERSIONING": True,
             "OPENEXR_NAMESPACE_VERSIONING": True,
             "CMAKE_INSTALL_PREFIX": self.package_folder,
             "USE_GLFW3": True,
             "GLFW3_USE_STATIC_LIBS": True
             })

        if "fPIC" in self.options.fields:
            cmake.definitions["CMAKE_POSITION_INDEPENDENT_CODE"] = self.options.fPIC

        cmake.configure(source_dir="{}/openvdb-{}".format(self.source_folder, self.version))
        cmake.build(target="install")

    def package(self):
        self.copy("LICENSE", src="{}/openvdb-{}".format(self.source_folder, self.version), dst="licenses")

        self.copy("*.h", dst="include", src="package/include", keep_path=True)
        self.copy("*", dst="lib", src="package/lib", keep_path=False)

    def package_info(self):
        self.cpp_info.cppflags.append("-std=c++11")

        if self.settings.os == "Windows" and not self.options.shared:
            self.cpp_info.libs = ["libopenvdb"]
        else:
            self.cpp_info.libs = ["openvdb"]

        self.cpp_info.defines = ["OPENVDB_3_ABI_COMPATIBLE", "OPENVDB_USE_BLOSC"]

        if self.options.shared:
            self.cpp_info.defines.append("OPENVDB_DLL")
        else:
            self.cpp_info.defines.append("OPENVDB_STATICLIB")

        if not self.options["OpenEXR"].shared:
            self.cpp_info.defines.append("OPENVDB_OPENEXR_STATICLIB")
