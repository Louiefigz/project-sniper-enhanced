using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;

internal static class WindowsMediaJail {
    const string ProfilePrefix = "ProjectSniper.MediaAdmission.";
    const uint ExtendedStartup = 0x00080000, Suspended = 0x00000004, NoWindow = 0x08000000;
    const uint StartfUseStdHandles = 0x00000100;
    const uint LimitProcessTime = 0x2, LimitActiveProcess = 0x8, LimitProcessMemory = 0x100;
    const uint LimitKillOnClose = 0x2000;
    const uint TokenQuery = 0x0008;
    const int SecurityCapabilitiesAttribute = 0x00020009;
    const int TokenIsAppContainer = 29;

    [StructLayout(LayoutKind.Sequential)] struct SecurityCapabilities {
        public IntPtr AppContainerSid, Capabilities;
        public int CapabilityCount, Reserved;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct StartupInfo {
        public int cb; public IntPtr reserved, desktop, title;
        public int x, y, xSize, ySize, xCountChars, yCountChars, fillAttribute;
        public uint flags; public short showWindow, reserved2; public IntPtr reserved3;
        public IntPtr stdInput, stdOutput, stdError;
    }
    [StructLayout(LayoutKind.Sequential)] struct StartupInfoEx {
        public StartupInfo StartupInfo; public IntPtr AttributeList;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInformation {
        public IntPtr Process, Thread; public int ProcessId, ThreadId;
    }
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long PerProcessTime, PerJobTime; public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet; public uint ActiveProcessLimit;
        public UIntPtr Affinity; public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters {
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic; public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }

    [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int CreateAppContainerProfile(
        string name, string display, string description, IntPtr capabilities, int count, out IntPtr sid);
    [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeriveAppContainerSidFromAppContainerName(
        string name, out IntPtr sid);
    [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeleteAppContainerProfile(string name);
    [DllImport("advapi32.dll", SetLastError=true)] static extern IntPtr FreeSid(IntPtr sid);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool ConvertSidToStringSid(IntPtr sid, out IntPtr text);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(
        IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(
        IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcessAsUser(
        IntPtr token, string application, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes,
        bool inherit, uint flags, IntPtr environment, string directory, ref StartupInfoEx startup,
        out ProcessInformation information);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, ref ExtendedLimits info, int length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(
        IntPtr job, int infoClass, out ExtendedLimits info, int length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int number);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(
        IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(
        IntPtr token, int informationClass, out int information, int length, out int returned);

    static void Check(bool value, string action) {
        if (!value) throw new Win32Exception(Marshal.GetLastWin32Error(), action);
    }
    static IntPtr ProfileSid(string name) {
        IntPtr sid;
        int result = CreateAppContainerProfile(name, "Project Sniper media admission",
            "No-network parser for untrusted media", IntPtr.Zero, 0, out sid);
        if (result == 183) result = DeriveAppContainerSidFromAppContainerName(name, out sid);
        if (result != 0) throw new Win32Exception(result, "creating the AppContainer profile");
        return sid;
    }
    static string SidText(IntPtr sid) {
        IntPtr raw; Check(ConvertSidToStringSid(sid, out raw), "formatting AppContainer SID");
        try { return Marshal.PtrToStringUni(raw); } finally { LocalFree(raw); }
    }
    static FileSystemAccessRule GrantRead(string path, string sidText) {
        if (path.Equals("NUL", StringComparison.OrdinalIgnoreCase)) return null;
        FileSecurity security = File.GetAccessControl(path);
        FileSystemAccessRule rule = new FileSystemAccessRule(new SecurityIdentifier(sidText),
            FileSystemRights.ReadAndExecute | FileSystemRights.ReadAttributes, AccessControlType.Allow);
        security.AddAccessRule(rule); File.SetAccessControl(path, security); return rule;
    }
    static void RevokeRead(string path, FileSystemAccessRule rule) {
        if (rule == null) return;
        FileSecurity security = File.GetAccessControl(path);
        security.RemoveAccessRuleSpecific(rule); File.SetAccessControl(path, security);
    }
    static void ProtectFile(string path) {
        SecurityIdentifier owner = WindowsIdentity.GetCurrent().User;
        FileSecurity security = new FileSecurity();
        security.SetOwner(owner); security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
            AccessControlType.Allow));
        File.SetAccessControl(path, security);
    }
    static string Quote(string value) {
        if (value.Length > 0 && value.IndexOfAny(new [] {' ', '\t', '"'}) < 0) return value;
        StringBuilder result = new StringBuilder("\""); int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') result.Append('\\', slashes * 2 + 1).Append(ch);
            else { result.Append('\\', slashes).Append(ch); }
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
    static StringBuilder Command(string[] values) {
        StringBuilder line = new StringBuilder();
        foreach (string value in values) { if (line.Length > 0) line.Append(' '); line.Append(Quote(value)); }
        return line;
    }
    static ExtendedLimits Limits(long memoryBytes, int cpuSeconds) {
        ExtendedLimits limits = new ExtendedLimits();
        limits.Basic.Flags = LimitKillOnClose | LimitActiveProcess | LimitProcessMemory | LimitProcessTime;
        limits.Basic.ActiveProcessLimit = 1;
        limits.Basic.PerProcessTime = cpuSeconds * 10000000L;
        limits.ProcessMemory = (UIntPtr)(ulong)memoryBytes;
        return limits;
    }
    static string Escape(string value) { return value.Replace("\\", "\\\\").Replace("\"", "\\\""); }
    static bool IsAppContainer(IntPtr process) {
        IntPtr token; Check(OpenProcessToken(process, TokenQuery, out token), "opening child token");
        try {
            int value, returned;
            Check(GetTokenInformation(token, TokenIsAppContainer, out value, sizeof(int), out returned),
                "checking child AppContainer token");
            return value != 0;
        } finally { CloseHandle(token); }
    }
    static ExtendedLimits VerifiedLimits(IntPtr job, long memory, int cpu) {
        ExtendedLimits observed;
        Check(QueryInformationJobObject(job,9,out observed,Marshal.SizeOf(typeof(ExtendedLimits)),IntPtr.Zero),
            "verifying Job Object limits");
        uint required = LimitKillOnClose | LimitActiveProcess | LimitProcessMemory | LimitProcessTime;
        bool valid = (observed.Basic.Flags & required) == required && observed.Basic.ActiveProcessLimit == 1
            && observed.Basic.PerProcessTime == cpu * 10000000L
            && observed.ProcessMemory.ToUInt64() == (ulong)memory;
        if (!valid) throw new InvalidOperationException("Job Object limits were not applied exactly");
        return observed;
    }
    static void WriteAttestation(string path, int pid, string sid, string input, long memory, int cpu,
            string decoder, string profileHash, string mode, bool appContainer) {
        string escaped = input.Replace("\\", "\\\\").Replace("\"", "\\\"");
        string json = "{\"sandboxed\":true,\"kind\":\"windows-appcontainer\",\"mode\":\"" + Escape(mode) + "\"," +
            "\"decoder\":\"" + Escape(decoder) + "\",\"input\":\"" + escaped + "\",\"inputResolved\":\"" + escaped + "\"," +
            "\"profileSha256\":\"" + Escape(profileHash) + "\",\"memoryMiB\":" + (memory / 1048576) + ",\"pid\":" + pid + "," +
            "\"appContainerSid\":\"" + sid + "\",\"writeDeniedOutsideProfile\":true,\"networkCapabilities\":0," +
            "\"tokenIsAppContainer\":" + appContainer.ToString().ToLowerInvariant() + ",\"ephemeralProfile\":true," +
            "\"job\":{\"activeProcessLimit\":1,\"cpuSeconds\":" + cpu + ",\"memoryLimitBytes\":" + memory + "}}";
        File.WriteAllText(path, json, new UTF8Encoding(false));
    }
    static int Run(string[] args) {
        int split = Array.IndexOf(args, "--");
        if (split < 0 || split == args.Length - 1) throw new ArgumentException("run needs -- PROGRAM ARGS");
        string input=args[1], attest=args[2]; long memory=long.Parse(args[3]); int cpu=int.Parse(args[4]);
        int wall=int.Parse(args[5]); string profileHash=args[6], decoder=args[7], mode=args[8];
        string[] command = new string[args.Length - split - 1]; Array.Copy(args, split + 1, command, 0, command.Length);
        string profileName=ProfilePrefix + Guid.NewGuid().ToString("N");
        IntPtr sid=ProfileSid(profileName), attributes=IntPtr.Zero, capabilities=IntPtr.Zero, job=IntPtr.Zero;
        FileSystemAccessRule inputRule=null, programRule=null; ProcessInformation process=new ProcessInformation();
        string sidText=SidText(sid);
        try {
            inputRule=GrantRead(input, sidText); programRule=GrantRead(command[0], sidText); IntPtr size=IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            attributes=Marshal.AllocHGlobal(size); Check(InitializeProcThreadAttributeList(attributes,1,0,ref size),"attribute list");
            SecurityCapabilities security=new SecurityCapabilities { AppContainerSid=sid };
            capabilities=Marshal.AllocHGlobal(Marshal.SizeOf(security)); Marshal.StructureToPtr(security,capabilities,false);
            Check(UpdateProcThreadAttribute(attributes,0,(IntPtr)SecurityCapabilitiesAttribute,capabilities,
                (IntPtr)Marshal.SizeOf(security),IntPtr.Zero,IntPtr.Zero),"AppContainer attribute");
            StartupInfoEx startup=new StartupInfoEx(); startup.StartupInfo.cb=Marshal.SizeOf(startup);
            startup.StartupInfo.flags=StartfUseStdHandles; startup.StartupInfo.stdInput=GetStdHandle(-10);
            startup.StartupInfo.stdOutput=GetStdHandle(-11); startup.StartupInfo.stdError=GetStdHandle(-12);
            job=CreateJobObject(IntPtr.Zero,null); Check(job != IntPtr.Zero,"creating Job Object");
            ExtendedLimits limits=Limits(memory,cpu);
            Check(SetInformationJobObject(job,9,ref limits,Marshal.SizeOf(limits)),"setting Job Object limits");
            Check(CreateProcessAsUser(IntPtr.Zero,command[0],Command(command),IntPtr.Zero,IntPtr.Zero,true,
                ExtendedStartup|Suspended|NoWindow,IntPtr.Zero,Environment.SystemDirectory,ref startup,out process),"sandboxed process");
            Check(AssignProcessToJobObject(job,process.Process),"assigning Job Object");
            VerifiedLimits(job,memory,cpu);
            ResumeThread(process.Thread);
            bool appContainer=IsAppContainer(process.Process);
            if (!appContainer) {
                TerminateJobObject(job,70);
                throw new InvalidOperationException("running child token is not an AppContainer");
            }
            WriteAttestation(attest,process.ProcessId,sidText,input,memory,cpu,decoder,profileHash,mode,appContainer);
            if (WaitForSingleObject(process.Process,(uint)wall*1000) == 258) {
                TerminateJobObject(job,124); Console.Error.WriteLine("SNIPER_TIMEOUT"); return 124;
            }
            uint code; Check(GetExitCodeProcess(process.Process,out code),"reading exit code");
            ExtendedLimits observed;
            if (QueryInformationJobObject(job,9,out observed,Marshal.SizeOf(typeof(ExtendedLimits)),IntPtr.Zero)
                    && observed.PeakProcessMemory.ToUInt64() >= (ulong)(memory * 9 / 10) && code != 0) {
                Console.Error.WriteLine("SNIPER_MEMORY_LIMIT"); return 137;
            }
            return unchecked((int)code);
        } finally {
            if (process.Thread != IntPtr.Zero) CloseHandle(process.Thread);
            if (process.Process != IntPtr.Zero) CloseHandle(process.Process);
            if (job != IntPtr.Zero) CloseHandle(job);
            if (attributes != IntPtr.Zero) { DeleteProcThreadAttributeList(attributes); Marshal.FreeHGlobal(attributes); }
            if (capabilities != IntPtr.Zero) Marshal.FreeHGlobal(capabilities);
            RevokeRead(command[0],programRule); RevokeRead(input,inputRule); FreeSid(sid);
            DeleteAppContainerProfile(profileName);
        }
    }
    public static int Main(string[] args) {
        try {
            if (args.Length == 1 && args[0] == "sid") {
                string name=ProfilePrefix + Guid.NewGuid().ToString("N"); IntPtr sid=ProfileSid(name);
                Console.WriteLine(SidText(sid)); FreeSid(sid); DeleteAppContainerProfile(name); return 0;
            }
            if (args.Length == 2 && args[0] == "protect") { ProtectFile(args[1]); return 0; }
            if (args.Length == 2 && args[0] == "read") { Console.Write(File.ReadAllText(args[1])); return 0; }
            if (args.Length >= 10 && args[0] == "run") return Run(args);
            Console.Error.WriteLine("usage: windows_media_jail sid | protect FILE | read FILE | run INPUT ATTEST BYTES CPU WALL PROFILE DECODER MODE -- PROGRAM ARGS");
            return 64;
        } catch (Exception error) { Console.Error.WriteLine("native-media-jail: " + error.Message); return 70; }
    }
}
