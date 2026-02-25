import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../ui/card';
import { Button } from '../../ui/button';
import { Input } from '../../ui/input';
import { Label } from '../../ui/label';
import { Tabs, TabsList, TabsTrigger } from '../../ui/tabs';
import { FileUpload } from '../FileUpload';
import { toast } from 'sonner';
import { Presentation, FileText, BarChart3, X } from 'lucide-react';
import { api } from '@/app/services/api';

const STORAGE_KEY = 'corpay_admin_switch_screen';

type SourceType = 'pdf' | 'powerbi';

interface StoredSwitchState {
  sourceType: SourceType;
  embedUrl: string;
  slideIntervalSeconds: number;
}

/** Extract a clean Power BI / embed URL. If user pastes full iframe embed code, strip tags and return only the src URL. */
function extractEmbedUrl(input: string): string {
  const raw = (input || '').trim();
  if (!raw) return '';
  // If pasted embed code contains iframe, extract src
  const iframeMatch = raw.match(/<iframe[^>]*\ssrc\s*=\s*["']([^"']+)["']/i) || raw.match(/src\s*=\s*["']([^"']+)["']/i);
  if (iframeMatch && iframeMatch[1]) {
    const url = iframeMatch[1].trim();
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
  }
  // Already a plain URL
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  return raw;
}

function loadStoredState(): StoredSwitchState {
  try {
    const s = localStorage.getItem(STORAGE_KEY);
    if (s) {
      const parsed = JSON.parse(s) as StoredSwitchState;
      if (parsed && typeof parsed.sourceType === 'string' && typeof parsed.embedUrl === 'string' && typeof parsed.slideIntervalSeconds === 'number') {
        return {
          sourceType: parsed.sourceType === 'powerbi' ? 'powerbi' : 'pdf',
          embedUrl: parsed.embedUrl || '',
          slideIntervalSeconds: Math.max(1, Math.min(300, parsed.slideIntervalSeconds || 5)),
        };
      }
    }
  } catch {
    // ignore
  }
  return { sourceType: 'pdf', embedUrl: '', slideIntervalSeconds: 5 };
}

function saveStoredState(state: StoredSwitchState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

export function SwitchScreenPage() {
  const [sourceType, setSourceType] = useState<SourceType>('pdf');
  const [pptFile, setPptFile] = useState<File | null>(null);
  const [uploadedPptUrl, setUploadedPptUrl] = useState<string | null>(null);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [embedUrl, setEmbedUrl] = useState<string>('');
  const [isUploadingPpt, setIsUploadingPpt] = useState(false);
  const [isSlideshowActive, setIsSlideshowActive] = useState(false);
  const [slideIntervalSeconds, setSlideIntervalSeconds] = useState<number>(5);
  const [loadingCurrentFile, setLoadingCurrentFile] = useState(true);

  // Device-specific state: restore from localStorage on mount (each device/branch has its own)
  useEffect(() => {
    const stored = loadStoredState();
    setSourceType(stored.sourceType);
    setEmbedUrl(stored.embedUrl);
    setSlideIntervalSeconds(stored.slideIntervalSeconds);
  }, []);

  // Load persisted slideshow file from backend on mount (so it survives refresh)
  useEffect(() => {
    api.get('dashboard/slideshow')
      .then((res) => {
        const data = res.data || {};
        if (data.file_url && data.file_name) {
          setUploadedFileName(data.file_name);
          setUploadedPptUrl(data.file_url);
        }
      })
      .catch(() => {})
      .finally(() => setLoadingCurrentFile(false));
  }, []);

  // Persist when user changes source type, embed URL, or interval (device-specific)
  useEffect(() => {
    saveStoredState({
      sourceType,
      embedUrl,
      slideIntervalSeconds,
    });
  }, [sourceType, embedUrl, slideIntervalSeconds]);

  const uploadPptFile = async (file: File): Promise<string | null> => {
    setIsUploadingPpt(true);
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');

    try {
      const formData = new FormData();
      formData.append('file', file);

      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      let response;
      try {
        response = await api.post('admin/slideshow/upload-dev', formData, {
          headers: {},
          timeout: 120000,
        });
      } catch (devError: any) {
        if (devError.response?.status === 401 || devError.response?.status === 403) {
          response = await api.post('admin/slideshow/upload', formData, {
            headers: { ...headers },
            timeout: 120000,
          });
        } else {
          throw devError;
        }
      }

      const fileUrl = response.data.file_url;
      const fileName = response.data.file_name || file?.name || null;
      setUploadedPptUrl(fileUrl);
      setUploadedFileName(fileName);
      toast.success('File uploaded successfully');
      return fileUrl;
    } catch (error: any) {
      console.error('Error uploading file:', error);
      toast.error(`Failed to upload file: ${error.message || 'Unknown error'}`);
      return null;
    } finally {
      setIsUploadingPpt(false);
    }
  };

  const handlePptFileSelect = async (file: File | null) => {
    setPptFile(file);
    if (file) {
      await uploadPptFile(file);
    } else {
      setUploadedPptUrl(null);
      setUploadedFileName(null);
    }
  };

  const handleDeleteSlideshowFile = async () => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    try {
      try {
        await api.delete('admin/slideshow/file-dev', { timeout: 120000 });
      } catch (devErr: any) {
        if (devErr.response?.status === 401 || devErr.response?.status === 403) {
          await api.delete('admin/slideshow/file', {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            timeout: 120000,
          });
        } else if (devErr.response?.status === 404) {
          setUploadedPptUrl(null);
          setUploadedFileName(null);
          setPptFile(null);
          toast.success('File removed. You can upload a new file.');
          return;
        } else throw devErr;
      }
      setUploadedPptUrl(null);
      setUploadedFileName(null);
      setPptFile(null);
      toast.success('File removed. You can upload a new file.');
    } catch (e: any) {
      if (e.response?.status === 404) {
        setUploadedPptUrl(null);
        setUploadedFileName(null);
        setPptFile(null);
        toast.success('File removed. You can upload a new file.');
        return;
      }
      toast.error(e.response?.data?.detail || 'Failed to remove file');
    }
  };

  const setSlideshowUrl = async (url: string): Promise<boolean> => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      await api.post('admin/slideshow/set-url-dev', { embed_url: url }, { headers: { 'Content-Type': 'application/json' }, timeout: 120000 });
      return true;
    } catch (devError: any) {
      if (devError.response?.status === 401 || devError.response?.status === 403) {
        try {
          await api.post('admin/slideshow/set-url', { embed_url: url }, { headers, timeout: 120000 });
          return true;
        } catch {
          toast.error('Authentication required. Please log in.');
          return false;
        }
      }
      throw devError;
    }
  };

  const handleStartSlideshow = async () => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    if (sourceType === 'powerbi') {
      const raw = embedUrl.trim();
      const url = extractEmbedUrl(raw);
      if (!url) {
        toast.error('Please enter a Power BI Embed URL (or paste the full embed iframe code)');
        return;
      }
      try {
        await setSlideshowUrl(url);
        const intervalSeconds = Math.max(1, Math.min(300, slideIntervalSeconds)) || 5;
        try {
          await api.post('admin/slideshow/start-dev', { interval_seconds: intervalSeconds }, { headers: { 'Content-Type': 'application/json' }, timeout: 120000 });
        } catch (devErr: any) {
          if (devErr.response?.status === 401 || devErr.response?.status === 403) {
            await api.post('admin/slideshow/start', { interval_seconds: intervalSeconds }, { headers, timeout: 120000 });
          } else throw devErr;
        }
        setIsSlideshowActive(true);
        toast.success('Switched main screen to slideshow');
      } catch (error: any) {
        console.error('Error starting slideshow:', error);
        toast.error(error.response?.data?.detail || `Failed to start slideshow: ${error.message || 'Unknown error'}`);
      }
      return;
    }

    if (!pptFile && !uploadedPptUrl) {
      toast.error('Please select a presentation file first');
      return;
    }

    let fileUrlToUse = uploadedPptUrl;
    if (pptFile && !uploadedPptUrl) {
      const uploadedUrl = await uploadPptFile(pptFile);
      if (!uploadedUrl) {
        toast.error('Failed to upload file. Please try again.');
        return;
      }
      fileUrlToUse = uploadedUrl;
    }

    if (!fileUrlToUse) {
      toast.error('No file available. Please upload a presentation first.');
      return;
    }

    try {
      const intervalSeconds = Math.max(1, Math.min(300, slideIntervalSeconds)) || 5;
      try {
        await api.post('admin/slideshow/start-dev', { interval_seconds: intervalSeconds }, { headers: { 'Content-Type': 'application/json' }, timeout: 120000 });
      } catch (devError: any) {
        if (devError.response?.status === 401 || devError.response?.status === 403) {
          await api.post('admin/slideshow/start', { interval_seconds: intervalSeconds }, { headers, timeout: 120000 });
        } else {
          throw devError;
        }
      }
      setIsSlideshowActive(true);
      toast.success('Switched main screen to slideshow');
    } catch (error: any) {
      console.error('Error starting slideshow:', error);
      toast.error(`Failed to start slideshow: ${error.message || 'Unknown error'}`);
    }
  };

  const handleStopSlideshow = async () => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
      try {
        await api.post('admin/slideshow/stop-dev', {}, { headers: { 'Content-Type': 'application/json' }, timeout: 120000 });
      } catch (devError: any) {
        if (devError.response?.status === 401 || devError.response?.status === 403) {
          await api.post('admin/slideshow/stop', {}, { headers, timeout: 120000 });
        } else {
          throw devError;
        }
      }
      setIsSlideshowActive(false);
      toast.success('Switched main screen back to dashboard');
    } catch (error: any) {
      console.error('Error stopping slideshow:', error);
      toast.error(`Failed to stop slideshow: ${error.message || 'Unknown error'}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl text-white mb-2">Switch Screen</h1>
          <p className="text-gray-400">
            Upload a PDF and switch the main dashboard screen to a full-screen slideshow.
          </p>
        </div>
      </div>

      <Card className="bg-white/10 border-white/20">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Presentation className="w-4 h-4" />
            Upload Presentation
          </CardTitle>
          <CardDescription className="text-gray-400">
            Upload a PDF file to display as a full-screen slideshow on the Frontend Dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Tabs value={sourceType} onValueChange={(v) => setSourceType(v as SourceType)} className="w-full">
            <TabsList className="bg-white/10 text-white">
              <TabsTrigger value="pdf" className="text-white data-[state=active]:bg-pink-600 data-[state=active]:text-white">
                <FileText className="w-4 h-4 mr-2" />
                PDF
              </TabsTrigger>
              <TabsTrigger value="powerbi" className="text-white data-[state=active]:bg-pink-600 data-[state=active]:text-white">
                <BarChart3 className="w-4 h-4 mr-2" />
                Power BI
              </TabsTrigger>
            </TabsList>

            {sourceType === 'pdf' && (
              <div className="mt-4 space-y-2">
                {loadingCurrentFile ? (
                  <p className="text-sm text-gray-400">Loading...</p>
                ) : uploadedPptUrl ? (
                  <div className="flex items-center justify-between gap-2 rounded-lg border border-white/20 bg-white/5 p-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-white truncate" title={uploadedFileName || undefined}>
                        {uploadedFileName || 'Current file'}
                      </p>
                      <p className="text-xs text-green-400">✓ File saved. It will stay until you remove it.</p>
                    </div>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={handleDeleteSlideshowFile}
                      className="shrink-0 text-red-400 hover:text-red-300 hover:bg-red-500/20"
                      title="Remove file (upload a new one after this)"
                    >
                      <X className="w-5 h-5" />
                    </Button>
                  </div>
                ) : (
                  <>
                    <FileUpload
                      selectedFile={pptFile}
                      onFileSelect={handlePptFileSelect}
                      onClear={() => {
                        setPptFile(null);
                        setUploadedPptUrl(null);
                        setUploadedFileName(null);
                      }}
                      label="Select PDF File"
                      accept={{
                        'application/pdf': ['.pdf'],
                      }}
                    />
                    {isUploadingPpt && (
                      <p className="text-sm text-gray-400">Uploading file...</p>
                    )}
                  </>
                )}
              </div>
            )}

            {sourceType === 'powerbi' && (
              <div className="mt-4 space-y-2">
                <Label htmlFor="embedUrl" className="text-white">
                  Embed URL
                </Label>
                <Input
                  id="embedUrl"
                  type="url"
                  placeholder="https://app.powerbi.com/... or paste full iframe embed code"
                  value={embedUrl}
                  onChange={(e) => setEmbedUrl(e.target.value)}
                  onPaste={(e) => {
                    const pasted = (e.clipboardData?.getData('text') || '').trim();
                    const cleaned = extractEmbedUrl(pasted);
                    if (cleaned && cleaned !== pasted) {
                      e.preventDefault();
                      setEmbedUrl(cleaned);
                    }
                  }}
                  className="bg-white/10 border-white/20 text-white"
                />
                <p className="text-xs text-gray-400">Paste the Power BI embed URL or full iframe embed code; the URL will be extracted automatically.</p>
              </div>
            )}
          </Tabs>

          {sourceType === 'pdf' && (
            <div className="space-y-2">
              <Label htmlFor="slideInterval" className="text-white">
                Slide interval (seconds)
              </Label>
              <Input
                id="slideInterval"
                type="number"
                min={1}
                max={300}
                value={slideIntervalSeconds}
                onChange={(e) => setSlideIntervalSeconds(Math.max(1, Math.min(300, Number(e.target.value) || 5)))}
                className="bg-white/10 border-white/20 text-white max-w-[120px]"
              />
              <p className="text-xs text-gray-400">How many seconds each slide is shown before moving to the next (1–300).</p>
            </div>
          )}

          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h4 className="text-white mb-2">Supported Formats:</h4>
            <ul className="text-sm text-gray-400 space-y-1">
              {sourceType === 'pdf' ? (
                <li>• PDF (.pdf) - No extra software needed</li>
              ) : (
                <li>• URL - Enter a valid Power BI Embed link</li>
              )}
            </ul>
            <p className="text-sm text-gray-400 mt-2">
              Click &quot;Switch to Present&quot; to replace the main dashboard with the presentation, and &quot;Switch back to Dashboard&quot;
              to return to the normal view.
            </p>
          </div>

          <div className="flex gap-4 mt-4">
            <Button
              onClick={handleStartSlideshow}
              disabled={
                (sourceType === 'pdf' && !pptFile && !uploadedPptUrl) ||
                (sourceType === 'powerbi' && !embedUrl.trim()) ||
                isUploadingPpt
              }
              className="flex-1 bg-pink-600 hover:bg-pink-700 text-white disabled:opacity-50"
            >
              {isUploadingPpt ? 'Uploading...' : 'Switch to Present'}
            </Button>
            <Button
              onClick={handleStopSlideshow}
              disabled={!isSlideshowActive}
              className="flex-1 bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
            >
              Switch back to Dashboard
            </Button>
            {sourceType === 'powerbi' && (
              <Button
                onClick={() => {
                  // Open the frontend dashboard in Power BI mode in a new tab.
                  window.open(`${import.meta.env.VITE_FRONTEND_URL || 'http://localhost:5175'}/?frontend=powerbi`, '_blank', 'noopener,noreferrer');
                }}
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white"
              >
                frontend+powerbi
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

