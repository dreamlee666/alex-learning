using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.ComponentModel;
using System.Windows.Forms;
using System.Text;
using System.Web.Script.Serialization;

// MIT. Captures only on explicit hotkey/selection; sends cropped pixels to loopback OCR.
class GameCompanion : Form {
    [DllImport("user32.dll")] static extern bool RegisterHotKey(IntPtr h,int id,uint mods,uint key);
    [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr h,int id);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    const string Origin="http://127.0.0.1:32194";
    Label status=new Label(); bool busy; static Mutex instance;
    GameCompanion() {
        Text="Alex · 游戏英语取词"; ClientSize=new Size(440,260); AutoScaleMode=AutoScaleMode.None;
        Font=new Font("Microsoft YaHei UI",10); FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false;
        var intro=new Label {Text="Ctrl + Alt + Q 框选文字；Esc 取消。\nCtrl + Alt + E 读取剪贴板（支持 TTime OCR）。",Left=20,Top=18,Width=400,Height=55}; Controls.Add(intro);
        var capture=new Button {Text="框选取词",Left=20,Top=85,Width=185,Height=40}; capture.Click+=delegate { CaptureRegion(); }; Controls.Add(capture);
        var open=new Button {Text="打开副屏伴读",Left=220,Top=85,Width=195,Height=40}; open.Click+=delegate {System.Diagnostics.Process.Start(Origin+"/study?mode=game");};Controls.Add(open);
        var paste=new Button {Text="读取剪贴板文字",Left=20,Top=135,Width=395,Height=36};paste.Click+=delegate{ReadClipboard();};Controls.Add(paste);
        status.SetBounds(20,185,395,65); status.Text="先启动课堂，再打开游戏伴读。仅在按快捷键时读取屏幕或剪贴板。";Controls.Add(status);
        Shown+=delegate {bool q=RegisterHotKey(Handle,1,0x4000|0x0001|0x0002,0x51);bool e=RegisterHotKey(Handle,2,0x4000|0x0001|0x0002,0x45);if(!q||!e)status.Text="部分快捷键被其他程序占用，请使用相应按钮。";if(Array.IndexOf(Environment.GetCommandLineArgs(),"--open")>=0)System.Diagnostics.Process.Start(Origin+"/study?mode=game");};
        FormClosed+=delegate {UnregisterHotKey(Handle,1);UnregisterHotKey(Handle,2);};
    }
    protected override void WndProc(ref Message m) {if(m.Msg==0x0312){if(m.WParam.ToInt32()==1)CaptureRegion();if(m.WParam.ToInt32()==2)ReadClipboard();}base.WndProc(ref m);}
    static string Send(string route,string contentType,byte[] payload){using(var client=new LocalClient()){client.Proxy=null;client.Encoding=Encoding.UTF8;var match=Regex.Match(client.DownloadString(Origin+"/study"),@"window\.SQE_CSRF='([^']+)'");if(!match.Success)throw new Exception("请先启动课堂。");client.Headers["X-SQE-CSRF"]=match.Groups[1].Value;client.Headers["Content-Type"]=contentType;return Encoding.UTF8.GetString(client.UploadData(Origin+route,"POST",payload));}}
    void ReadClipboard(){if(busy)return;string text;try{text=Clipboard.GetText().Trim();}catch(Exception ex){status.Text=ex.Message;return;}if(text.Length==0||text.Length>16000){status.Text="请先复制文字（最多 16000 字符），或使用 TTime 的静默截图 OCR。";return;}busy=true;status.Text="正在传入副屏…";var worker=new BackgroundWorker();worker.DoWork+=delegate(object s,DoWorkEventArgs e){e.Result=Send("/study/companion/text-capture","application/json",Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(new {text=text})));};worker.RunWorkerCompleted+=delegate(object s,RunWorkerCompletedEventArgs e){busy=false;status.Text=e.Error==null?"剪贴板文字已送到游戏伴读。点击单词问老师。":"读取失败："+e.Error.Message;worker.Dispose();};worker.RunWorkerAsync();}
    void CaptureRegion() {
        if(busy)return; busy=true; Hide();
        BeginInvoke((MethodInvoker)delegate {
            byte[] png=null;
            try {using(var selector=new Selection()){if(selector.ShowDialog()==DialogResult.OK)png=selector.Png;}}
            catch(Exception ex){status.Text="截图失败："+ex.Message;}
            Show(); if(png==null){busy=false;return;}status.Text="正在本机识别，完成后查看副屏。";
            var worker=new BackgroundWorker();worker.DoWork+=delegate(object s,DoWorkEventArgs e) {
                try {using(var client=new LocalClient()) {
                    client.Proxy=null;
                    string html=client.DownloadString(Origin+"/study");
                    var match=Regex.Match(html,@"window\.SQE_CSRF='([^']+)'");
                    if(!match.Success)throw new Exception("课堂未准备好，请先启动课堂。");
                    client.Headers["X-SQE-CSRF"]=match.Groups[1].Value;client.Headers["Content-Type"]="image/png";
                    client.UploadData(Origin+"/study/companion/capture","POST",png);e.Result="已取词。请在副屏「游戏伴读」查看原文并点击单词。";
                }} catch(WebException ex){e.Result="识别未完成。检查课堂是否已启动，或缩小框选区域。"+ex.Message;}
                catch(Exception ex){e.Result=ex.Message;}
            };
            worker.RunWorkerCompleted+=delegate(object s,RunWorkerCompletedEventArgs e){busy=false;status.Text=e.Error==null?(string)e.Result:"识别失败，请重试。";worker.Dispose();};worker.RunWorkerAsync();
        });
    }
    [STAThread] static void Main(string[] args) {
        if(args.Length>0 && args[0]=="--self-test"){Environment.Exit(Regex.IsMatch("window.SQE_CSRF='local-test';",@"window\.SQE_CSRF='([^']+)'")?0:1);return;}
        try {SetProcessDpiAwarenessContext(new IntPtr(-4));}catch(EntryPointNotFoundException){SetProcessDPIAware();}
        bool fresh;instance=new Mutex(true,"Local\\AlexLearningGameCompanion",out fresh);if(!fresh){MessageBox.Show("英语取词助手已经运行。快捷键为 Ctrl + Alt + Q。");return;}
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new GameCompanion());instance.ReleaseMutex();instance.Dispose();
    }
}
class LocalClient : WebClient {protected override WebRequest GetWebRequest(Uri address){var request=base.GetWebRequest(address);request.Timeout=120000;return request;}}
class Selection : Form {
    Bitmap desktop; Point start; Rectangle selection; bool dragging; public byte[] Png;
    public Selection() {
        AutoScaleMode=AutoScaleMode.None; FormBorderStyle=FormBorderStyle.None;StartPosition=FormStartPosition.Manual;
        Bounds=SystemInformation.VirtualScreen;TopMost=true;DoubleBuffered=true;Cursor=Cursors.Cross;KeyPreview=true;
        desktop=new Bitmap(Width,Height);using(var g=Graphics.FromImage(desktop))g.CopyFromScreen(Bounds.Location,Point.Empty,Bounds.Size);
        KeyDown+=delegate(object s,KeyEventArgs e){if(e.KeyCode==Keys.Escape){DialogResult=DialogResult.Cancel;Close();}};
    }
    protected override void OnPaint(PaintEventArgs e) {
        e.Graphics.DrawImageUnscaled(desktop,0,0);using(var dim=new SolidBrush(Color.FromArgb(100,0,0,0)))e.Graphics.FillRectangle(dim,ClientRectangle);
        if(selection.Width>0 && selection.Height>0){e.Graphics.DrawImage(desktop,selection,selection,GraphicsUnit.Pixel);using(var pen=new Pen(Color.LimeGreen,2))e.Graphics.DrawRectangle(pen,selection);}
        using(var brush=new SolidBrush(Color.White))e.Graphics.DrawString("拖动框选游戏文字 · Esc 取消",Font,brush,18,18);
    }
    protected override void OnMouseDown(MouseEventArgs e){if(e.Button!=MouseButtons.Left)return;start=e.Location;dragging=true;Capture=true;}
    protected override void OnMouseMove(MouseEventArgs e){if(!dragging)return;selection=Rectangle.Intersect(ClientRectangle,new Rectangle(Math.Min(start.X,e.X),Math.Min(start.Y,e.Y),Math.Abs(start.X-e.X),Math.Abs(start.Y-e.Y)));Invalidate();}
    protected override void OnMouseUp(MouseEventArgs e){if(!dragging)return;dragging=false;Capture=false;if(selection.Width<8 || selection.Height<8)return;
        using(var crop=desktop.Clone(selection,PixelFormat.Format24bppRgb))using(var output=new MemoryStream()) {
            double scale=Math.Min(1,2200.0/Math.Max(crop.Width,crop.Height));
            using(var resized=new Bitmap(crop,new Size(Math.Max(1,(int)(crop.Width*scale)),Math.Max(1,(int)(crop.Height*scale)))))resized.Save(output,ImageFormat.Png);
            Png=output.ToArray();
        }DialogResult=DialogResult.OK;Close();
    }
    protected override void Dispose(bool disposing){if(disposing && desktop!=null){desktop.Dispose();desktop=null;}base.Dispose(disposing);}
}
