using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.ComponentModel;
using System.Windows.Forms;

// MIT. Small visible launcher; all classroom code ships in App/.
class ClassroomLauncher : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly Label status = new Label();
    readonly TextBox output = new TextBox();
    readonly Button start = new Button();
    readonly Button stop = new Button();
    bool busy = false;
    bool running = false;
    bool closing = false;
    static Mutex instance;

    ClassroomLauncher() {
        Text = "Alex · 通用学习课堂";
        ClientSize = new Size(660, 490);
        Font = new Font("Microsoft YaHei UI", 10);
        BackColor = Color.FromArgb(248, 247, 243);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        var title = new Label {Text="Alex · 你的学习空间", Left=26, Top=24, Width=610, Height=42, Font=new Font(Font.FontFamily,18,FontStyle.Bold)};
        Controls.Add(title);
        status.SetBounds(28, 77, 602, 38);
        status.Text="正在启动……首次使用需要联网准备音频工具。";
        Controls.Add(status);
        output.SetBounds(28, 122, 602, 177);
        output.Multiline=true; output.ReadOnly=true; output.ScrollBars=ScrollBars.Vertical;
        output.BackColor=Color.White; output.BorderStyle=BorderStyle.FixedSingle;
        Controls.Add(output);
        start.Text="启动 / 打开课堂"; start.SetBounds(28,315,175,38);
        start.Click += delegate { if(running) Open("http://127.0.0.1:32194/study"); else Run("--start --open"); };
        Controls.Add(start);
        var settings=new Button {Text="账号与声音设置", Left=215, Top=315, Width=175, Height=38};
        settings.Click += delegate { if(running) Open("http://127.0.0.1:32194/"); else MessageBox.Show("请先启动课堂。",Text); };
        Controls.Add(settings);
        stop.Text="停止课堂";stop.SetBounds(403,315,115,38);
        stop.Click += delegate { Run("--stop"); }; Controls.Add(stop);
        var logs=new Button {Text="查看日志", Left=530, Top=315, Width=100, Height=38};
        logs.Click += delegate { Open(Path.Combine(root,"App","deployment")); };Controls.Add(logs);
        var help = new LinkLabel {Text="使用说明与第三方许可", Left=28, Top=376, Width=270, Height=25};
        help.LinkClicked += delegate { Open(Path.Combine(root,"使用说明.html")); };Controls.Add(help);
        Controls.Add(new Label {Text="免费分享版 · Windows x64 · v0.6.0", Left=328,Top=376,Width=310,Height=26,ForeColor=Color.DimGray});
        var game=new Button {Text="游戏伴读 / 快捷取词", Left=28, Top=425, Width=240, Height=38};
        game.Click += delegate {if(running){Open("http://127.0.0.1:32194/study?mode=game");Open(Path.Combine(root,"Alex-Game-Companion.exe"));}else MessageBox.Show("请先启动课堂。",Text);}; Controls.Add(game);
        var reader=new Button {Text="文档伴读 / 学习笔记", Left=286, Top=425, Width=240, Height=38};
        reader.Click += delegate {if(running)Open("http://127.0.0.1:32194/study?mode=reading");else MessageBox.Show("请先启动课堂。",Text);};Controls.Add(reader);
        Shown += delegate { Run("--start --open"); };
        FormClosing += OnClosing;
    }

    static void Open(string target) {
        try { Process.Start(new ProcessStartInfo(target) {UseShellExecute=true}); }
        catch(Exception ex) {MessageBox.Show(ex.Message,"无法打开");}
    }

    static string Quote(string value) { return "\"" + value.Replace("\"","\\\"").TrimEnd('\\') + "\""; }

    ProcessStartInfo Controller(string arguments) {
        var info=new ProcessStartInfo(Path.Combine(root,"runtime","python","python.exe"),
            "-X utf8 -u " + Quote(Path.Combine(root,"launcher","bootstrap.py")) + " " + arguments);
        info.WorkingDirectory=root; info.UseShellExecute=false;info.CreateNoWindow=true;
        info.RedirectStandardOutput=true;info.RedirectStandardError=true;
        info.StandardOutputEncoding=Encoding.UTF8;info.StandardErrorEncoding=Encoding.UTF8;
        info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
        return info;
    }

    void Append(string line) {
        if(IsDisposed || closing) return;
        BeginInvoke((MethodInvoker)delegate {if(!IsDisposed){output.AppendText(line+Environment.NewLine);status.Text=line;}});
    }

    void Run(string arguments) {
        if(busy) return;
        busy=true;start.Enabled=false;stop.Enabled=false;
        var worker=new BackgroundWorker();
        worker.DoWork += delegate(object sender, DoWorkEventArgs args) {
            try {
                using(var process=new Process {StartInfo=Controller(arguments)}) {
                    process.OutputDataReceived += delegate(object s,DataReceivedEventArgs e) {if(e.Data!=null) Append(e.Data);};
                    process.ErrorDataReceived += delegate(object s,DataReceivedEventArgs e) {if(e.Data!=null) Append(e.Data);};
                    process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();
                    args.Result=process.ExitCode;
                }
            } catch(Exception ex) {Append("启动出错："+ex.Message);args.Result=1;}
        };
        worker.RunWorkerCompleted += delegate(object sender,RunWorkerCompletedEventArgs args) {
            busy=false;start.Enabled=true;stop.Enabled=true;
            if(args.Error==null && (int)args.Result==0) running=!arguments.Contains("--stop");
            else {running=false;status.Text="启动未完成。请检查网络或点击“查看日志”，然后重试。";}
        };
        worker.RunWorkerAsync();
    }

    void OnClosing(object sender,FormClosingEventArgs args) {
        if(busy) {args.Cancel=true;status.Text="正在准备或停止服务，请等待完成后关闭。";return;}
        closing=true;
        if(running) {
            try {using(var p=Process.Start(Controller("--stop"))) {if(!p.WaitForExit(12000))p.Kill();}} catch {}
        }
    }

    [STAThread]
    static int Main(string[] args) {
        string root=AppDomain.CurrentDomain.BaseDirectory;
        if(args.Length>0 && args[0]=="--check") return File.Exists(Path.Combine(root,"launcher","bootstrap.py")) && File.Exists(Path.Combine(root,"runtime","python","python.exe")) ? 0 : 1;
        // Exercise the same launch/stop controller from the compiled EXE for support.
        // No browser or GUI is opened by this explicit diagnostics mode.
        if(args.Length>0 && args[0]=="--diagnose") {
            using(var form=new ClassroomLauncher()) {
                string report=""; int code=0;
                foreach(string command in new string[]{"--start","--stop"}) {
                    try {
                        using(var p=Process.Start(form.Controller(command))) {
                            report+=p.StandardOutput.ReadToEnd()+p.StandardError.ReadToEnd();p.WaitForExit();
                            if(p.ExitCode!=0) code=p.ExitCode;
                        }
                    } catch(Exception ex) {report+=ex.Message;code=1;}
                }
                File.WriteAllText(Path.Combine(root,"launcher","diagnostics.log"),report,Encoding.UTF8);
                return code;
            }
        }
        bool created;
        using(var hash=System.Security.Cryptography.SHA256.Create()) {
            instance=new Mutex(true,"Local\\SQEClassroom-"+BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-",""),out created);
        }
        if(!created) {Open("http://127.0.0.1:32194/study");return 0;}
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new ClassroomLauncher());instance.ReleaseMutex();instance.Dispose();return 0;
    }
}
