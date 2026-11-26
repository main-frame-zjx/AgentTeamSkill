using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

internal static class DesktopLauncher
{
#if HANDBOOK
    const string Action = "handbook";
#elif BOARD
    const string Action = "board";
#elif STOP
    const string Action = "stop";
#else
#error Select a desktop action when compiling.
#endif

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            string directory = AppDomain.CurrentDomain.BaseDirectory;
            string controller = Path.Combine(directory, "desktop-services.ps1");
            if (!File.Exists(controller))
                throw new FileNotFoundException("AgentTeam desktop controller is missing.", controller);

            var options = new List<string>();
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (arg == "-NoBrowser")
                    options.Add(arg);
                else
                {
                    int port;
                    if ((arg != "-BoardPort" && arg != "-HandbookPort") || ++i >= args.Length ||
                        !int.TryParse(args[i], NumberStyles.None, CultureInfo.InvariantCulture, out port) ||
                        port < 1 || port > 65535)
                        throw new ArgumentException("Invalid desktop launcher option: " + arg);
                    options.Add(arg);
                    options.Add(port.ToString(CultureInfo.InvariantCulture));
                }
            }

            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File \"" +
                            controller + "\" " + Action + " -FromDesktop " + string.Join(" ", options),
                WorkingDirectory = directory,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            if (Array.IndexOf(args, "-NoBrowser") < 0)
                MessageBox.Show(error.Message, "AgentTeam", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
