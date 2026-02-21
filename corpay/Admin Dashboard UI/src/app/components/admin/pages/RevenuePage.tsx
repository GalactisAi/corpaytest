import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../ui/card';
import { Button } from '../../ui/button';
import { Input } from '../../ui/input';
import { Label } from '../../ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../ui/tabs';
import { FileUpload } from '../FileUpload';
import { PowerBIEmbed } from '../PowerBIEmbed';
import { sharePriceService } from '@/app/services/apiService';
import { toast } from 'sonner';
import { Upload, Plus, TrendingUp, DollarSign, Trash2, PieChart, X } from 'lucide-react';
import axios from 'axios';
import { api, getOrigin } from '@/app/services/api';

export function RevenuePage() {
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [currentRevenueFile, setCurrentRevenueFile] = useState<{ file_name: string; file_id: number } | null>(null);
  const [loadingCurrentRevenueFile, setLoadingCurrentRevenueFile] = useState(true);
  const [pptFile, setPptFile] = useState<File | null>(null);
  const [manualRevenue, setManualRevenue] = useState('');
  const [lastMonth, setLastMonth] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  
  // Share price manual entry state
  const [manualSharePrice, setManualSharePrice] = useState('');
  const [manualSharePriceChange, setManualSharePriceChange] = useState('');
  const [isSavingSharePrice, setIsSavingSharePrice] = useState(false);
  
  // Payments manual entry state
  const [paymentCardTitle, setPaymentCardTitle] = useState(
    localStorage.getItem('paymentCardTitle') || 'Customisable card 1'
  );
  const [manualPaymentAmount, setManualPaymentAmount] = useState('');
  const [manualPaymentTransactions, setManualPaymentTransactions] = useState('');
  const [isSavingPayment, setIsSavingPayment] = useState(false);
  
  // System performance manual entry state
  const [systemPerformanceCardTitle, setSystemPerformanceCardTitle] = useState(
    localStorage.getItem('systemPerformanceCardTitle') || 'Customisable card 2'
  );
  const [manualUptime, setManualUptime] = useState('');
  const [manualSuccessRate, setManualSuccessRate] = useState('');
  const [isSavingSystem, setIsSavingSystem] = useState(false);

  // Customizable subtitles (labels shown on front card: subtitle 1 = amount label, subtitle 2 = transactions label)
  const [paymentAmountSubtitle, setPaymentAmountSubtitle] = useState(
    () => localStorage.getItem('paymentAmountSubtitle') || 'Amount Processed'
  );
  const [paymentTransactionsSubtitle, setPaymentTransactionsSubtitle] = useState(
    () => localStorage.getItem('paymentTransactionsSubtitle') || 'Transactions'
  );
  const [systemUptimeSubtitle, setSystemUptimeSubtitle] = useState(
    () => localStorage.getItem('systemUptimeSubtitle') || 'Enter uptime percentage (e.g., 99.985)'
  );
  const [systemSuccessRateSubtitle, setSystemSuccessRateSubtitle] = useState(
    () => localStorage.getItem('systemSuccessRateSubtitle') || 'Enter success rate percentage (e.g., 99.62)'
  );
  
  // Share price state
  const [sharePrice, setSharePrice] = useState<{ price: number; change: number; changePercent: number; timestamp: string } | null>(null);
  const [isLoadingSharePrice, setIsLoadingSharePrice] = useState(false);

  // Revenue summary state (matches main dashboard)
  const [revenueSummary, setRevenueSummary] = useState<{ total_amount: number; percentage_change: number } | null>(null);
  const [isLoadingRevenue, setIsLoadingRevenue] = useState(false);

  // Charts (pie proportions) state moved from ChartsPage
  interface ChartCategory {
    category: string;
    percentage: number;
  }
  const [categories, setCategories] = useState<ChartCategory[]>([
    { category: '', percentage: 0 }
  ]);
  const [isSavingCharts, setIsSavingCharts] = useState(false);
  
  // Power BI view states
  const [showProportionsDashboard, setShowProportionsDashboard] = useState(false);
  const [showTrendsDashboard, setShowTrendsDashboard] = useState(false);
  
  // Slideshow state
  const [isSlideshowActive, setIsSlideshowActive] = useState(false);
  const [uploadedPptUrl, setUploadedPptUrl] = useState<string | null>(null);
  const [isUploadingPpt, setIsUploadingPpt] = useState(false);

  // Persist editable card titles locally
  useEffect(() => {
    localStorage.setItem('paymentCardTitle', paymentCardTitle);
  }, [paymentCardTitle]);

  useEffect(() => {
    localStorage.setItem('systemPerformanceCardTitle', systemPerformanceCardTitle);
  }, [systemPerformanceCardTitle]);

  // Persist customizable subtitles to localStorage
  useEffect(() => {
    localStorage.setItem('paymentAmountSubtitle', paymentAmountSubtitle);
  }, [paymentAmountSubtitle]);
  useEffect(() => {
    localStorage.setItem('paymentTransactionsSubtitle', paymentTransactionsSubtitle);
  }, [paymentTransactionsSubtitle]);
  useEffect(() => {
    localStorage.setItem('systemUptimeSubtitle', systemUptimeSubtitle);
  }, [systemUptimeSubtitle]);
  useEffect(() => {
    localStorage.setItem('systemSuccessRateSubtitle', systemSuccessRateSubtitle);
  }, [systemSuccessRateSubtitle]);
  
  // Load current revenue state from backend (production uses GET /api/dashboard/revenue; no current-file endpoint)
  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get('dashboard/revenue', { timeout: 120000 });
        if (res.data?.file_name) {
          setCurrentRevenueFile({
            file_name: res.data.file_name,
            file_id: res.data.file_id ?? 0,
          });
        }
      } catch {
        // no file or API down: leave currentRevenueFile null
      } finally {
        setLoadingCurrentRevenueFile(false);
      }
    };
    load();
  }, []);

  // Load card titles and subtitles from backend config on mount
  useEffect(() => {
    const loadCardTitlesFromBackend = async () => {
      const token = localStorage.getItem('authToken') || localStorage.getItem('token');
      if (!token) return;

      try {
        const response = await api.get('admin/config', {
          headers: { Authorization: `Bearer ${token}` },
          timeout: 120000,
        });
        const data = response.data || {};
        if (data.dashboard_payments_title) {
          setPaymentCardTitle(data.dashboard_payments_title);
        }
        if (data.dashboard_system_title) {
          setSystemPerformanceCardTitle(data.dashboard_system_title);
        }
        if (data.dashboard_payments_amount_subtitle != null && data.dashboard_payments_amount_subtitle !== '') {
          setPaymentAmountSubtitle(data.dashboard_payments_amount_subtitle);
        }
        if (data.dashboard_payments_transactions_subtitle != null && data.dashboard_payments_transactions_subtitle !== '') {
          setPaymentTransactionsSubtitle(data.dashboard_payments_transactions_subtitle);
        }
        if (data.dashboard_system_uptime_subtitle != null && data.dashboard_system_uptime_subtitle !== '') {
          setSystemUptimeSubtitle(data.dashboard_system_uptime_subtitle);
        }
        if (data.dashboard_system_success_rate_subtitle != null && data.dashboard_system_success_rate_subtitle !== '') {
          setSystemSuccessRateSubtitle(data.dashboard_system_success_rate_subtitle);
        }
      } catch (error) {
        console.error('Failed to load card titles from backend config:', error);
      }
    };

    loadCardTitlesFromBackend();
  }, []);

  const saveCardTitlesToBackend = async (): Promise<boolean> => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    if (!token) {
      toast.error('Please log in to save card titles and subtitles to the main dashboard.');
      return false;
    }

    try {
      await api.put(
        'admin/config',
        {
          dashboard_payments_title: paymentCardTitle,
          dashboard_system_title: systemPerformanceCardTitle,
          dashboard_payments_amount_subtitle: paymentAmountSubtitle,
          dashboard_payments_transactions_subtitle: paymentTransactionsSubtitle,
          dashboard_system_uptime_subtitle: systemUptimeSubtitle,
          dashboard_system_success_rate_subtitle: systemSuccessRateSubtitle,
        },
        {
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          timeout: 120000,
        }
      );
      toast.success('Card titles and subtitles saved. Main dashboard will update within 30 seconds or after refresh.');
      return true;
    } catch (error) {
      console.error('Failed to save card titles to backend config:', error);
      toast.error('Failed to save card titles to backend');
      return false;
    }
  };
  
  // Handle PPT file upload to backend
  const handlePptFileSelect = async (file: File | null) => {
    setPptFile(file);
    if (file) {
      await uploadPptFile(file);
    } else {
      setUploadedPptUrl(null);
    }
  };
  
  // Upload PPT file to backend
  const   uploadPptFile = async (file: File): Promise<string | null> => {
    setIsUploadingPpt(true);
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const headers: Record<string, string> = { 'Content-Type': 'multipart/form-data' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      
      const response = await api.post('admin/slideshow/upload', formData, {
        headers,
        timeout: 120000,
      });
      
      const fileUrl = response.data.file_url;
      setUploadedPptUrl(fileUrl);
      toast.success('PPT file uploaded successfully');
      return fileUrl;
    } catch (error: any) {
      console.error('Error uploading PPT file:', error);
      toast.error(`Failed to upload PPT file: ${error.message || 'Unknown error'}`);
      return null;
    } finally {
      setIsUploadingPpt(false);
    }
  };
  
  // Start slideshow on frontend dashboard
  const handleStartSlideshow = async () => {
    if (!pptFile && !uploadedPptUrl) {
      toast.error('Please select a PPT file first');
      return;
    }
    
    // If file is selected but not uploaded yet, upload it first
    let fileUrlToUse = uploadedPptUrl;
    if (pptFile && !uploadedPptUrl) {
      const uploadedUrl = await uploadPptFile(pptFile);
      if (!uploadedUrl) {
        toast.error('Failed to upload PPT file. Please try again.');
        return;
      }
      fileUrlToUse = uploadedUrl;
    }
    
    if (!fileUrlToUse) {
      toast.error('No PPT file available. Please upload a file first.');
      return;
    }
    
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      
      await api.post('admin/slideshow/start', {}, { headers, timeout: 120000 });
      
      setIsSlideshowActive(true);
      toast.success('Slideshow started on frontend dashboard');
    } catch (error: any) {
      console.error('Error starting slideshow:', error);
      toast.error(`Failed to start slideshow: ${error.message || 'Unknown error'}`);
    }
  };
  
  // Stop slideshow on frontend dashboard
  const handleStopSlideshow = async () => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      
      await api.post('admin/slideshow/stop', {}, { headers, timeout: 120000 });
      
      setIsSlideshowActive(false);
      toast.success('Slideshow stopped on frontend dashboard');
    } catch (error: any) {
      console.error('Error stopping slideshow:', error);
      toast.error(`Failed to stop slideshow: ${error.message || 'Unknown error'}`);
    }
  };

  // Load share price on mount and set up auto-refresh
  useEffect(() => {
    loadSharePrice();
    // Refresh share price every 30 seconds
    const interval = setInterval(loadSharePrice, 30000);
    return () => clearInterval(interval);
  }, []);

  // Load revenue summary on mount and auto-refresh
  useEffect(() => {
    loadRevenueSummary();
    const interval = setInterval(loadRevenueSummary, 30000);
    return () => clearInterval(interval);
  }, []);

  const loadSharePrice = async () => {
    setIsLoadingSharePrice(true);
    try {
      const data = await sharePriceService.getSharePrice();
      setSharePrice(data);
    } catch (error) {
      toast.error('Failed to load share price');
    } finally {
      setIsLoadingSharePrice(false);
    }
  };

  const loadRevenueSummary = async () => {
    setIsLoadingRevenue(true);
    try {
      const response = await api.get('dashboard/revenue', { timeout: 120000 });
      if (response.data) {
        setRevenueSummary({
          total_amount: Number(response.data.total_amount) || 0,
          percentage_change: Number(response.data.percentage_change) || 0,
        });
      }
    } catch (error) {
      console.error('Failed to load revenue summary:', error);
      toast.error('Failed to load revenue summary');
    } finally {
      setIsLoadingRevenue(false);
    }
  };

  // Charts helpers (from ChartsPage)
  const addCategory = () => {
    setCategories([...categories, { category: '', percentage: 0 }]);
  };

  const removeCategory = (index: number) => {
    if (categories.length > 1) {
      setCategories(categories.filter((_, i) => i !== index));
    } else {
      toast.error('At least one category is required');
    }
  };

  const updateCategory = (index: number, field: keyof ChartCategory, value: string | number) => {
    const updated = [...categories];
    updated[index] = { ...updated[index], [field]: value };
    setCategories(updated);
  };

  const handleSaveCharts = async () => {
    // Validate all fields are filled
    if (categories.some(cat => !cat.category || cat.percentage <= 0)) {
      toast.error('Please fill in all category names and percentages (greater than 0)');
      return;
    }

    // Validate percentages sum to 100
    const totalPercentage = categories.reduce((sum, cat) => sum + Number(cat.percentage), 0);
    if (Math.abs(totalPercentage - 100) > 0.01) {
      toast.error(`Percentages must sum to 100%. Current total: ${totalPercentage.toFixed(2)}%`);
      return;
    }

    setIsSavingCharts(true);

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');

    // Default colors for categories (cycling through brand colors)
    const colors = ['#981239', '#3D1628', '#E6E8E7', '#BE1549', '#8B1538', '#5A0F24'];
    
    const proportionsData = categories.map((cat, index) => ({
      category: cat.category,
      percentage: Number(cat.percentage),
      color: colors[index % colors.length]
    }));

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await axios.get(`${getOrigin()}/health`, { timeout: 120000 });
    } catch (healthError: any) {
      console.error('Backend health check failed:', healthError.message);
      toast.error('Backend not reachable. Please ensure the backend server is running.');
      setIsSavingCharts(false);
      return;
    }

    try {
      await api.post('admin/revenue/proportions/manual', { proportions: proportionsData }, { headers, timeout: 120000 });

      // Successfully saved to backend
      localStorage.setItem('chartProportions', JSON.stringify(proportionsData));
      window.dispatchEvent(new CustomEvent('chartProportionsUpdated', {
        detail: proportionsData
      }));
      toast.success('Chart proportions saved successfully to backend');
      setIsSavingCharts(false);
      return;
    } catch (apiError: any) {
      console.error('Backend API error:', {
        message: apiError.message,
        code: apiError.code,
        status: apiError.response?.status,
        statusText: apiError.response?.statusText,
        data: apiError.response?.data,
      });

      // Fallback to localStorage if API fails
      localStorage.setItem('chartProportions', JSON.stringify(proportionsData));
      window.dispatchEvent(new CustomEvent('chartProportionsUpdated', {
        detail: proportionsData
      }));
      toast.warning('Backend API unavailable. Data saved locally. Please check backend connection.');
      setIsSavingCharts(false);
    }
  };

  const handleExcelUpload = async () => {
    if (!excelFile) {
      toast.error('Please select a file');
      return;
    }

    setIsUploading(true);
    try {
      const token = localStorage.getItem('authToken') || localStorage.getItem('token');
      const formData = new FormData();
      formData.append('file', excelFile);

      const headers: Record<string, string> = { 'Content-Type': 'multipart/form-data' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await api.post('admin/revenue/upload', formData, { headers, timeout: 120000 });

      console.log('Revenue Excel upload response:', response.data);

      try {
        const [trendsRes, proportionsRes] = await Promise.all([
          api.get('dashboard/revenue-trends', { timeout: 120000 }),
          api.get('dashboard/revenue-proportions', { timeout: 120000 }),
        ]);

        if (trendsRes.data) {
          localStorage.setItem('revenueTrends', JSON.stringify(trendsRes.data));
          window.dispatchEvent(new CustomEvent('revenueTrendsUpdated', {
            detail: trendsRes.data,
          }));
        }

        if (proportionsRes.data) {
          localStorage.setItem('chartProportions', JSON.stringify(proportionsRes.data));
          window.dispatchEvent(new CustomEvent('chartProportionsUpdated', {
            detail: proportionsRes.data,
          }));
        }
      } catch (syncError) {
        console.error('Error syncing dashboard after Excel upload:', syncError);
      }

      toast.success('Revenue data uploaded and processed successfully');
      setExcelFile(null);
      setCurrentRevenueFile({
        file_name: excelFile.name,
        file_id: response.data?.file_id ?? 0,
      });
    } catch (error) {
      console.error('Error uploading revenue Excel file:', error);
      const message = (error as any)?.response?.data?.detail || (error as Error).message || 'Upload failed';
      toast.error(`Upload failed: ${message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteRevenueFile = async () => {
    // Production backend has no current-file endpoint; clear local state only
    setCurrentRevenueFile(null);
    setExcelFile(null);
    toast.success('Revenue file cleared. You can upload a new Excel file.');
  };

  const handleManualEntry = async () => {
    if (!manualRevenue || !lastMonth) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsUploading(true);
    // Convert user input (in millions) to full dollars
    // User enters "400" meaning $400M, we convert to 400000000
    const revenueInMillions = parseFloat(manualRevenue);
    const revenueInDollars = revenueInMillions * 1000000;
    
    const revenueData = {
      total_amount: revenueInDollars,
      percentage_change: parseFloat(lastMonth),
      last_updated: new Date().toISOString()
    };
    
    console.log(`Converting ${revenueInMillions}M to $${revenueInDollars.toLocaleString()}`);

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await axios.get(`${getOrigin()}/health`, { timeout: 120000 });
    } catch (healthError: any) {
      console.error('Backend health check failed:', healthError.message);
      toast.error('Backend not reachable. Please ensure the backend server is running.');
    }

    try {
      const response = await api.post(
        'admin/revenue/manual',
        {
          total_amount: revenueData.total_amount,
          percentage_change: revenueData.percentage_change,
        },
        { headers, timeout: 120000 }
      );
      console.log('Backend response:', response.data);
      
      // Successfully saved to backend
      // Also save to localStorage as backup and trigger update
      localStorage.setItem('revenueData', JSON.stringify(revenueData));
      window.dispatchEvent(new CustomEvent('revenueDataUpdated', {
        detail: revenueData
      }));
      
      toast.success('Revenue data saved successfully to backend');
      setManualRevenue('');
      setLastMonth('');
      setIsUploading(false);
      return;
    } catch (apiError: any) {
      console.error('Backend API error:', {
        message: apiError.message,
        code: apiError.code,
        status: apiError.response?.status,
        statusText: apiError.response?.statusText,
        data: apiError.response?.data,
        config: {
          url: apiError.config?.url,
          method: apiError.config?.method
        }
      });

      // Check if it's a network/connection error
      if (apiError.code === 'ECONNABORTED' || apiError.message === 'Network Error' || 
          apiError.code === 'ERR_NETWORK' || apiError.code === 'ECONNREFUSED') {
        
        console.warn('Backend unavailable, saving to localStorage as fallback');
        
        // Save to localStorage for frontend dashboard to read
        localStorage.setItem('revenueData', JSON.stringify(revenueData));
        
        // Trigger custom event for cross-origin communication
        window.dispatchEvent(new CustomEvent('revenueDataUpdated', {
          detail: revenueData
        }));
        
        toast.warning('Backend unavailable - saved locally. Please ensure backend is running.');
        setManualRevenue('');
        setLastMonth('');
        setIsUploading(false);
        return;
      }
      
      // Check if it's an authentication error
      if (apiError.response?.status === 401 || apiError.response?.status === 403) {
        const errorDetail = apiError.response?.data?.detail || 'Authentication required';
        toast.error(`Authentication failed: ${errorDetail}. Saving locally as fallback.`);
        
        // Save to localStorage as fallback
        localStorage.setItem('revenueData', JSON.stringify(revenueData));
        window.dispatchEvent(new CustomEvent('revenueDataUpdated', {
          detail: revenueData
        }));
        
        setManualRevenue('');
        setLastMonth('');
        setIsUploading(false);
        return;
      }
      
      // For other errors, show the error but don't save locally
      const errorMessage = apiError.response?.data?.detail || apiError.message || 'Failed to save revenue data';
      toast.error(`Backend error: ${errorMessage}`);
      console.error('Revenue save error:', apiError);
      setIsUploading(false);
    }
  };

  const handleSharePriceEntry = async () => {
    if (!manualSharePrice || !manualSharePriceChange) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsSavingSharePrice(true);
    const sharePriceData = {
      price: parseFloat(manualSharePrice),
      change_percentage: parseFloat(manualSharePriceChange),
    };

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await axios.get(`${getOrigin()}/health`, { timeout: 120000 });
    } catch (healthError: any) {
      toast.error('Backend not reachable. Please ensure the backend server is running.');
      setIsSavingSharePrice(false);
      return;
    }

    try {
      await api.post(
        'admin/revenue/share-price/manual',
        { price: sharePriceData.price, change_percentage: sharePriceData.change_percentage },
        { headers, timeout: 120000 }
      );

      // Successfully saved to backend
      localStorage.setItem('sharePriceData', JSON.stringify(sharePriceData));
      window.dispatchEvent(new CustomEvent('sharePriceDataUpdated', {
        detail: sharePriceData
      }));
      toast.success('Share price data saved successfully to backend');
      setManualSharePrice('');
      setManualSharePriceChange('');
      setIsSavingSharePrice(false);
      return;
    } catch (apiError: any) {
      console.error('Backend API error:', {
        message: apiError.message,
        code: apiError.code,
        status: apiError.response?.status,
        statusText: apiError.response?.statusText,
        data: apiError.response?.data,
      });

      // Fallback to localStorage if API fails
      localStorage.setItem('sharePriceData', JSON.stringify(sharePriceData));
      window.dispatchEvent(new CustomEvent('sharePriceDataUpdated', {
        detail: sharePriceData
      }));
      toast.warning('Backend API unavailable. Data saved locally. Please check backend connection.');
      setManualSharePrice('');
      setManualSharePriceChange('');
      setIsSavingSharePrice(false);
    }
  };

  const handlePaymentEntry = async () => {
    if (!manualPaymentAmount || !manualPaymentTransactions) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsSavingPayment(true);
    const today = new Date().toISOString().split('T')[0];
    const paymentData = {
      amount_processed: parseFloat(manualPaymentAmount) * 10000000, // Convert Cr to actual amount
      transaction_count: parseInt(manualPaymentTransactions),
      date: today
    };

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await axios.get(`${getOrigin()}/health`, { timeout: 120000 });
    } catch (healthError: any) {
      toast.error('Backend not reachable. Please ensure the backend server is running.');
      setIsSavingPayment(false);
      return;
    }

    try {
      await api.post('admin/payments', paymentData, { headers, timeout: 120000 });
      toast.success('Customizable card 1 updated');
      await saveCardTitlesToBackend();
      setManualPaymentAmount('');
      setManualPaymentTransactions('');
    } catch (authError: any) {
      if (authError.response?.status === 401 || authError.response?.status === 403) {
        toast.error('Authentication required. Please log in.');
        setIsSavingPayment(false);
        return;
      }
      const errorMessage = authError.response?.data?.detail || authError.message || 'Failed to save payment data';
      toast.error(`Error: ${errorMessage}`);
    } finally {
      setIsSavingPayment(false);
    }
  };

  const handleSystemPerformanceEntry = async () => {
    if (!manualUptime || !manualSuccessRate) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsSavingSystem(true);
    const systemData = {
      uptime_percentage: parseFloat(manualUptime),
      success_rate: parseFloat(manualSuccessRate)
    };

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await axios.get(`${getOrigin()}/health`, { timeout: 120000 });
    } catch (healthError: any) {
      toast.error('Backend not reachable. Please ensure the backend server is running.');
      setIsSavingSystem(false);
      return;
    }

    try {
      await api.post('admin/system', systemData, { headers, timeout: 120000 });
      toast.success('Customizable card 2 updated');
      setManualUptime('');
      setManualSuccessRate('');
    } catch (authError: any) {
      if (authError.response?.status === 401 || authError.response?.status === 403) {
        toast.error('Authentication required. Please log in.');
      } else {
        const errorMessage = authError.response?.data?.detail || authError.message || 'Failed to save system performance data';
        toast.error(`Error: ${errorMessage}`);
      }
    } finally {
      setIsSavingSystem(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl text-white mb-2">Revenue Management</h1>
          <p className="text-gray-400">Upload revenue data via Excel, PPT, Power BI, or enter manually</p>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Revenue Summary Display */}
          {revenueSummary && (
            <Card className="bg-white/10 border-white/20 min-w-[220px]">
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <DollarSign className="w-4 h-4 text-pink-500" />
                      <span className="text-xs text-gray-400">Total Revenue</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-2xl font-bold text-white">
                        ${revenueSummary.total_amount > 0 ? (revenueSummary.total_amount / 1_000_000).toFixed(0) : '0'}M
                      </span>
                      <span className="text-xs text-green-400">
                        ▲ {revenueSummary.percentage_change.toFixed(1)}% vs last month
                      </span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Tabs defaultValue="manual" className="w-full">
        <TabsList className="bg-white/10 text-white">
          <TabsTrigger value="manual" className="text-white data-[state=active]:bg-pink-600 data-[state=active]:text-white">
            <Plus className="w-4 h-4 mr-2" />
            Manual Entry
          </TabsTrigger>
          <TabsTrigger value="charts" className="text-white data-[state=active]:bg-pink-600 data-[state=active]:text-white">
            <PieChart className="w-4 h-4 mr-2" />
            Charts
          </TabsTrigger>
          <TabsTrigger value="trends" className="text-white data-[state=active]:bg-pink-600 data-[state=active]:text-white">
            <TrendingUp className="w-4 h-4 mr-2" />
            Revenue Trends
          </TabsTrigger>
        </TabsList>

        <TabsContent value="manual" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="bg-white/10 border-white/20">
              <CardHeader>
                <CardTitle className="text-white">Manual Revenue Entry</CardTitle>
                <CardDescription className="text-gray-400">
                  Enter revenue data manually for quick updates
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="revenue" className="text-white">Total Revenue (in Millions)</Label>
                  <Input
                    id="revenue"
                    type="number"
                    value={manualRevenue}
                    onChange={(e) => setManualRevenue(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                  />
                  <p className="text-xs text-gray-400 mt-1">Enter value in millions (e.g., 976 for $976M)</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="lastMonth" className="text-white">% vs Last Month</Label>
                  <Input
                    id="lastMonth"
                    type="number"
                    step="0.01"
                    value={lastMonth}
                    onChange={(e) => setLastMonth(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                <Button 
                  onClick={handleManualEntry}
                  disabled={isUploading}
                  className="w-full bg-pink-600 hover:bg-pink-700"
                >
                  {isUploading ? 'Saving...' : 'Save Revenue Data'}
                </Button>
              </CardContent>
            </Card>

            {/* Manual Share Price Entry Card */}
            <Card className="bg-white/10 border-white/20">
              <CardHeader>
                <CardTitle className="text-white">Manual Share Price Entry</CardTitle>
                <CardDescription className="text-gray-400">
                  Enter share price data manually for quick updates
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="sharePrice" className="text-white">Share Price</Label>
                  <Input
                    id="sharePrice"
                    type="number"
                    step="0.01"
                    value={manualSharePrice}
                    onChange={(e) => setManualSharePrice(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="sharePriceChange" className="text-white">% Change</Label>
                  <Input
                    id="sharePriceChange"
                    type="number"
                    step="0.01"
                    value={manualSharePriceChange}
                    onChange={(e) => setManualSharePriceChange(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                <Button 
                  onClick={handleSharePriceEntry}
                  disabled={isSavingSharePrice}
                  className="w-full bg-pink-600 hover:bg-pink-700"
                >
                  {isSavingSharePrice ? 'Saving...' : 'Save Share Price Data'}
                </Button>
              </CardContent>
            </Card>

            {/* Payments Processed Today Entry Card */}
            <Card className="bg-white/10 border-white/20">
              <CardHeader>
                <CardTitle className="text-white">{paymentCardTitle}</CardTitle>
                <CardDescription className="text-gray-400">
                  Enter data manually for quick updates
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* 1. Card title – changes "Payments Processed Today" name on the front card */}
                <div className="space-y-2">
                  <Label htmlFor="paymentCardTitle" className="text-white">Card Title</Label>
                  <Input
                    id="paymentCardTitle"
                    type="text"
                    value={paymentCardTitle}
                    onChange={(e) => setPaymentCardTitle(e.target.value)}
                    onBlur={() => saveCardTitlesToBackend()}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., Customisable card 1"
                  />
                </div>

                {/* 2. Subtitle 1 – label shown on front card for amount (e.g. "Amount Processed") */}
                <div className="space-y-2">
                  <Label htmlFor="paymentAmountSubtitle" className="text-white">Subtitle 1</Label>
                  <Input
                    id="paymentAmountSubtitle"
                    type="text"
                    placeholder="e.g., Amount Processed"
                    value={paymentAmountSubtitle}
                    onChange={(e) => setPaymentAmountSubtitle(e.target.value)}
                    onBlur={saveCardTitlesToBackend}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                {/* 3. Subtitle 2 – label shown on front card for transactions (e.g. "Transactions") */}
                <div className="space-y-2">
                  <Label htmlFor="paymentTransactionsSubtitle" className="text-white">Subtitle 2</Label>
                  <Input
                    id="paymentTransactionsSubtitle"
                    type="text"
                    placeholder="e.g., Transactions"
                    value={paymentTransactionsSubtitle}
                    onChange={(e) => setPaymentTransactionsSubtitle(e.target.value)}
                    onBlur={saveCardTitlesToBackend}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                {/* 4. Value for subtitle 1 – number shown under subtitle 1 on card (e.g. ₹12.0 Cr) */}
                <div className="space-y-2">
                  <Label htmlFor="paymentAmount" className="text-white">Value for subtitle 1</Label>
                  <Input
                    id="paymentAmount"
                    type="text"
                    value={manualPaymentAmount}
                    onChange={(e) => setManualPaymentAmount(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., 12"
                  />
                  <p className="text-xs text-gray-400">Shown on card as value under &quot;{paymentAmountSubtitle || 'Subtitle 1'}&quot; (e.g. ₹12.0 Cr)</p>
                </div>

                {/* 5. Value for subtitle 2 – number shown under subtitle 2 on card (e.g. 12) */}
                <div className="space-y-2">
                  <Label htmlFor="paymentTransactions" className="text-white">Value for subtitle 2</Label>
                  <Input
                    id="paymentTransactions"
                    type="text"
                    value={manualPaymentTransactions}
                    onChange={(e) => setManualPaymentTransactions(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., 12"
                  />
                  <p className="text-xs text-gray-400">Shown on card as value under &quot;{paymentTransactionsSubtitle || 'Subtitle 2'}&quot;</p>
                </div>

                <Button 
                  onClick={handlePaymentEntry}
                  disabled={isSavingPayment}
                  className="w-full bg-pink-600 hover:bg-pink-700"
                >
                  {isSavingPayment ? 'Updating...' : 'Update'}
                </Button>
              </CardContent>
            </Card>

            {/* System Performance Entry Card */}
            <Card className="bg-white/10 border-white/20">
              <CardHeader>
                <CardTitle className="text-white">{systemPerformanceCardTitle}</CardTitle>
                <CardDescription className="text-gray-400">
                  Enter data manually for quick updates
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="systemPerformanceCardTitle" className="text-white">Card Title</Label>
                  <Input
                    id="systemPerformanceCardTitle"
                    type="text"
                    value={systemPerformanceCardTitle}
                    onChange={(e) => setSystemPerformanceCardTitle(e.target.value)}
                    onBlur={saveCardTitlesToBackend}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., Customisable card 2"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="systemUptimeSubtitle" className="text-white">Subtitle 1</Label>
                  <Input
                    id="systemUptimeSubtitle"
                    type="text"
                    placeholder="e.g., Uptime"
                    value={systemUptimeSubtitle}
                    onChange={(e) => setSystemUptimeSubtitle(e.target.value)}
                    onBlur={saveCardTitlesToBackend}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="systemSuccessRateSubtitle" className="text-white">Subtitle 2</Label>
                  <Input
                    id="systemSuccessRateSubtitle"
                    type="text"
                    placeholder="e.g., Success Rate"
                    value={systemSuccessRateSubtitle}
                    onChange={(e) => setSystemSuccessRateSubtitle(e.target.value)}
                    onBlur={saveCardTitlesToBackend}
                    className="bg-white/10 border-white/20 text-white"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="uptime" className="text-white">Value for subtitle 1</Label>
                  <Input
                    id="uptime"
                    type="text"
                    value={manualUptime}
                    onChange={(e) => setManualUptime(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., 12"
                  />
                  <p className="text-xs text-gray-400">Shown on card as value under &quot;{systemUptimeSubtitle || 'Subtitle 1'}&quot;</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="successRate" className="text-white">Value for subtitle 2</Label>
                  <Input
                    id="successRate"
                    type="text"
                    value={manualSuccessRate}
                    onChange={(e) => setManualSuccessRate(e.target.value)}
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="e.g., 12"
                  />
                  <p className="text-xs text-gray-400">Shown on card as value under &quot;{systemSuccessRateSubtitle || 'Subtitle 2'}&quot;</p>
                </div>

                <Button 
                  onClick={handleSystemPerformanceEntry}
                  disabled={isSavingSystem}
                  className="w-full bg-pink-600 hover:bg-pink-700"
                >
                  {isSavingSystem ? 'Updating...' : 'Update'}
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Charts management moved from sidebar */}
        <TabsContent value="charts" className="mt-6">
          <div className="space-y-6">
            <Card className="bg-white/10 border-white/20">
              <CardHeader>
                <CardTitle className="text-white">Charts</CardTitle>
                <CardDescription className="text-gray-400">
                  Manage and customize pie chart categories and proportions.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {categories.map((category, index) => (
                  <div key={index} className="flex gap-3 items-end p-4 bg-white/5 rounded-lg border border-white/10">
                    <div className="flex-1 space-y-2">
                      <Label htmlFor={`category-${index}`} className="text-white">
                        Category Name
                      </Label>
                      <Input
                        id={`category-${index}`}
                        type="text"
                        placeholder="e.g., Fleet, Corporate, Lodging"
                        value={category.category}
                        onChange={(e) => updateCategory(index, 'category', e.target.value)}
                        className="bg-white/10 border-white/20 text-white"
                      />
                    </div>
                    <div className="w-32 space-y-2">
                      <Label htmlFor={`percentage-${index}`} className="text-white">
                        Percentage (%)
                      </Label>
                      <Input
                        id={`percentage-${index}`}
                        type="number"
                        step="0.01"
                        min="0"
                        max="100"
                        placeholder="0.00"
                        value={category.percentage || ''}
                        onChange={(e) => updateCategory(index, 'percentage', parseFloat(e.target.value) || 0)}
                        className="bg-white/10 border-white/20 text-white"
                      />
                    </div>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => removeCategory(index)}
                      disabled={categories.length === 1}
                      className="bg-red-500/20 border-red-500/30 text-red-300 hover:bg-red-500/30 hover:border-red-500/50"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                ))}

                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={addCategory}
                    className="bg-white/10 border-white/20 text-white hover:bg-white/20"
                  >
                    <Plus className="w-4 h-4 mr-2" />
                    Add Category
                  </Button>
                </div>

                <div className="pt-4 border-t border-white/10">
                  <div className="flex items-center justify-between mb-4">
                    <p className="text-white font-semibold">Total Percentage:</p>
                    <p className={`text-lg font-bold ${
                      Math.abs(categories.reduce((sum, cat) => sum + Number(cat.percentage || 0), 0) - 100) < 0.01
                        ? 'text-green-400' 
                        : 'text-red-400'
                    }`}>
                      {categories.reduce((sum, cat) => sum + Number(cat.percentage || 0), 0).toFixed(2)}%
                    </p>
                  </div>
                  <Button
                    onClick={handleSaveCharts}
                    disabled={isSavingCharts}
                    className="w-full bg-pink-600 hover:bg-pink-700"
                  >
                    {isSavingCharts ? 'Saving...' : 'Save Chart Proportions'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="trends" className="mt-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl text-white mb-1">Revenue Trends Dashboard</h2>
                <p className="text-gray-400 text-sm">View revenue trends and monthly performance</p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowTrendsDashboard(false)}
                  className="bg-white/10 border-white/20 text-white hover:bg-white/20 hover:border-white/30"
                >
                  <Upload className="w-4 h-4 mr-2" />
                  Upload Excel Instead
                </Button>
              </div>
            </div>
            
            {showTrendsDashboard ? (
              <PowerBIEmbed
                title="Revenue Trends"
                description="Monthly revenue trends and performance metrics"
                height="700px"
              />
            ) : (
              <Card className="bg-white/10 border-white/20">
                <CardHeader>
                  <CardTitle className="text-white">Upload Revenue Trends Excel</CardTitle>
                  <CardDescription className="text-gray-400">
                    Upload an Excel file containing revenue trends by month, or use Power BI dashboard above. Trend data persists until you remove it.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {loadingCurrentRevenueFile ? (
                    <p className="text-sm text-gray-400">Loading...</p>
                  ) : currentRevenueFile ? (
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-white/20 bg-white/5 p-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-white truncate" title={currentRevenueFile.file_name}>
                          {currentRevenueFile.file_name}
                        </p>
                        <p className="text-xs text-green-400">✓ Trend data from this file. Remove to upload a new file.</p>
                      </div>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={handleDeleteRevenueFile}
                        className="shrink-0 text-red-400 hover:text-red-300 hover:bg-red-500/20"
                        title="Remove file (upload a new one after this)"
                      >
                        <X className="w-5 h-5" />
                      </Button>
                    </div>
                  ) : (
                    <>
                      <FileUpload
                        selectedFile={excelFile}
                        onFileSelect={setExcelFile}
                        onClear={() => setExcelFile(null)}
                        label="Select Excel File"
                      />
                      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                        <h4 className="text-white mb-2">Expected Format:</h4>
                        <ul className="text-sm text-gray-400 space-y-1">
                          <li>• Column A: Month</li>
                          <li>• Column B: Revenue Amount</li>
                          <li>• Column C: Growth Rate (%)</li>
                        </ul>
                      </div>
                      <Button 
                        onClick={handleExcelUpload}
                        disabled={!excelFile || isUploading}
                        className="w-full bg-pink-600 hover:bg-pink-700"
                      >
                        {isUploading ? 'Uploading...' : 'Upload Trends Data'}
                      </Button>
                    </>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
