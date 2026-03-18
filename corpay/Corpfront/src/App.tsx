import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Linkedin } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, ResponsiveContainer } from 'recharts';
import { StatCard } from './components/StatCard';
import { LinkedInPostCard } from './components/LinkedInPostCard';
import { EmployeeMilestone } from './components/EmployeeMilestone';
import { CompanyAnnouncement } from './components/CompanyAnnouncement';
import { NewsroomCard } from './components/NewsroomCard';
import { ResourceCard } from './components/ResourceCard';
import { FullScreenSlideshow } from './components/FullScreenSlideshow';
import { dashboardApi, apiBaseURL } from './services/api';
import corpayLogo from './assets/895e861462df910e5a72623a9b8e8a744f2ab348.png';
import crossBorderGlimpse from './assets/aaf95357c3595e79ededa176ac81f9fc76f886b5.png';
import backgroundPattern from './assets/8a99135dee321789a4c9c35b37279ec88120fc47.png';
import axios from 'axios';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Return true only if s looks like a real date; reject junk like "is showing". */
function isValidDateString(s: string): boolean {
  if (!s || typeof s !== 'string') return false;
  const t = s.trim().toLowerCase();
  if (['is showing', 'showing', 'show', 'view', 'read more', '—', '-'].includes(t) || t.length > 50) return false;
  const hasYear = /\b(19|20)\d{2}\b/.test(s);
  const hasMonthOrNumeric = /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}/i.test(s) || /\d{1,2}[\s/\-]\d{1,2}[\s/\-]\d{2,4}/.test(s);
  return hasYear && (hasMonthOrNumeric || /^\d{4}-\d{2}-\d{2}/.test(s));
}

/** Extract a date string from title/excerpt when API doesn't return a separate date. */
function extractDateFromTitle(text: string): string {
  if (!text || typeof text !== 'string') return '';
  // Month name + day + year (e.g. "February 4, 2026", "Jan 15, 2025")
  const m = text.match(
    /\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b/i
  );
  if (m) return m[0].trim();
  // ISO date YYYY-MM-DD
  const iso = text.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);
  if (iso) {
    const month = MONTH_NAMES[parseInt(iso[2], 10) - 1];
    return month ? `${month} ${parseInt(iso[3], 10)}, ${iso[1]}` : iso[0];
  }
  return '';
}

/** Extract a display date from article URL (e.g. /2025/01/15/article-slug). */
function extractDateFromUrl(url: string): string {
  if (!url || typeof url !== 'string') return '';
  const m = url.match(/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:\/|$|-|\s)/);
  if (!m) return '';
  const [, year, monthStr, dayStr] = m;
  const month = parseInt(monthStr, 10);
  const day = parseInt(dayStr, 10);
  if (month < 1 || month > 12 || day < 1 || day > 31) return '';
  const monthName = MONTH_NAMES[month - 1];
  return monthName ? `${monthName} ${day}, ${year}` : '';
}

/** Pick the best display date: API date (publication date) or URL only. Do not use title/excerpt — headlines often contain the event date (e.g. "Results on February 4, 2026"), not the publication date (e.g. January 21, 2026). */
function newsroomDisplayDate(item: { date?: string; title?: string; excerpt?: string; url?: string }): string {
  const raw = (item.date || '').trim();
  if (raw && isValidDateString(raw)) return raw;
  return extractDateFromUrl(item.url || '');
}

const revenueData = [
  { month: 'Jan', value: 70 },
  { month: 'Feb', value: 72 },
  { month: 'Mar', value: 75 },
  { month: 'Apr', value: 92, highlight: true },
  { month: 'May', value: 73 },
  { month: 'Jun', value: 87 },
  { month: 'Jul', value: 89 },
  { month: 'Aug', value: 72 },
  { month: 'Sep', value: 105, highlight: true },
  { month: 'Oct', value: 88 },
  { month: 'Nov', value: 91 },
  { month: 'Dec', value: 83 },
];

const engagementData = [
  { day: 'Mon', value: 1800 },
  { day: 'Tue', value: 1900 },
  { day: 'Wed', value: 1700 },
  { day: 'Thu', value: 2000 },
  { day: 'Fri', value: 2100 },
];

// Default revenue proportions (shape matches backend API: category, percentage, color)
const pieData = [
  { category: 'Fleet', percentage: 40, color: '#981239' },
  { category: 'Corporate', percentage: 35, color: '#3D1628' },
  { category: 'Lodging', percentage: 25, color: '#E6E8E7' },
];






export default function App() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef2 = useRef<HTMLDivElement>(null);
  const resourcesScrollRef = useRef<HTMLDivElement>(null);
  const resourcesScrollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const newsroomScrollRef = useRef<HTMLDivElement>(null);
  const newsroomScrollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const milestonesScrollRef = useRef<HTMLDivElement>(null);
  const fetchSharePriceDataRef = useRef<(() => Promise<void>) | null>(null);
  
  // State for API data
  const [loading, setLoading] = useState(true);
  const [revenue, setRevenue] = useState({ total_amount: 0, percentage_change: 0 });
  const [sharePrice, setSharePrice] = useState({ price: 0, change_percentage: 0 });
  const [revenueTrends, setRevenueTrends] = useState(revenueData);
  const [revenueProportions, setRevenueProportions] = useState(pieData);
  const [posts, setPosts] = useState<Array<{ author: string; timeAgo: string; content: string; image?: string; likes?: number; comments?: number; postUrl?: string }>>([]);
  const [crossBorderPostsList, setCrossBorderPostsList] = useState<Array<{ author: string; timeAgo: string; content: string; image?: string; likes?: number; comments?: number; postUrl?: string }>>([]);
  const [milestonesList, setMilestonesList] = useState<Array<{
    name: string;
    description: string;
    avatar: string;
    borderColor: string;
    backgroundColor: string;
    emoji?: string;
  }>>([]);
  const [payments, setPayments] = useState({ amount_processed: 428000000, transaction_count: 19320 });
  const [systemPerformance, setSystemPerformance] = useState({ uptime_percentage: 99.985, success_rate: 99.62 });
  const [newsroomItems, setNewsroomItems] = useState<Array<{
    title: string;
    url: string;
    date?: string;
    category?: string;
    excerpt?: string;
  }>>([]);
  const [resourceItems, setResourceItems] = useState<Array<{
    title: string;
    url: string;
    date?: string;
    category?: string;
    excerpt?: string;
  }>>([]);
  const [cardTitles, setCardTitles] = useState<{
    payments: string;
    systemPerformance: string;
    paymentsAmountSubtitle: string;
    paymentsTransactionsSubtitle: string;
    systemUptimeSubtitle: string;
    systemSuccessRateSubtitle: string;
  }>({
    payments: 'Payments Processed Today',
    systemPerformance: 'System Performance',
    paymentsAmountSubtitle: 'Amount Processed',
    paymentsTransactionsSubtitle: 'Transactions',
    systemUptimeSubtitle: 'System Uptime',
    systemSuccessRateSubtitle: 'Success Rate',
  });
  
  // Slideshow state (PDF/file or Power BI URL)
  const [slideshowState, setSlideshowState] = useState<{
    is_active: boolean;
    type: 'file' | 'url';
    file_url: string | null;
    embed_url: string | null;
    file_name: string | null;
    interval_seconds?: number;
  }>({
    is_active: false,
    type: 'file',
    file_url: null,
    embed_url: null,
    file_name: null,
    interval_seconds: 5,
  });

  // Special mode: when opened with ?frontend=powerbi, replace key metric cards
  // with a single Power BI dashboard card (using the admin-configured URL).
  const isFrontendPowerBI =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('frontend') === 'powerbi';

  const powerBIEmbedUrl =
    slideshowState.type === 'url'
      ? (slideshowState.embed_url || slideshowState.file_url)
      : null;

  // Top 3 months by revenue value for bar coloring
  const topThreeMonthsByValue = (() => {
    if (!revenueTrends || revenueTrends.length === 0) return [] as string[];
    const sorted = [...revenueTrends].sort((a, b) => (b.value || 0) - (a.value || 0));
    return sorted.slice(0, 3).map(item => item.month);
  })();

  // Function to fetch revenue data
  const fetchRevenueData = async () => {
    try {
      console.log('[Revenue] Fetching from API...');
      const revenueRes = await dashboardApi.getRevenue();
      console.log('[Revenue] Full API Response:', revenueRes);
      console.log('[Revenue] Response status:', revenueRes.status);
      console.log('[Revenue] Response data:', revenueRes.data);
      
      // Axios wraps the response, so the actual data is in revenueRes.data
      const responseData = revenueRes.data;
      if (responseData) {
        console.log('[Revenue] Parsed Response Data:', responseData);
        const newRevenue = {
          total_amount: Number(responseData.total_amount) || 0,
          percentage_change: Number(responseData.percentage_change) || 0
        };
        console.log('[Revenue] Setting state to:', newRevenue);
        console.log('[Revenue] Will display as:', `$${(newRevenue.total_amount / 1000000).toFixed(0)}M`);
        setRevenue(newRevenue);
        // Also save to localStorage as backup
        localStorage.setItem('revenueData', JSON.stringify(newRevenue));
      } else {
        console.warn('[Revenue] No data in API response:', revenueRes);
      }
    } catch (error) {
      console.error('[Revenue] Error fetching from API:', error);
      // Fallback to localStorage if API fails
      const localRevenue = localStorage.getItem('revenueData');
      if (localRevenue) {
        try {
          const parsed = JSON.parse(localRevenue);
          console.log('[Revenue] Using localStorage data:', parsed);
          setRevenue({
            total_amount: parsed.total_amount || 0,
            percentage_change: parsed.percentage_change || 0
          });
        } catch (e) {
          console.error('[Revenue] Failed to parse localStorage:', e);
        }
      }
    }
  };

  const fetchCardTitles = async () => {
    try {
      const res = await dashboardApi.getCardTitles();
      const data = res?.data ?? {};
      const paymentsTitle = data.payments_title ?? 'Payments Processed Today';
      const systemTitle = data.system_performance_title ?? 'System Performance';
      const amountSub = data.payments_amount_subtitle ?? 'Amount Processed';
      const transactionsSub = data.payments_transactions_subtitle ?? 'Transactions';
      const uptimeSub = data.system_uptime_subtitle ?? 'System Uptime';
      const successRateSub = data.system_success_rate_subtitle ?? 'Success Rate';
      setCardTitles({
        payments: paymentsTitle,
        systemPerformance: systemTitle,
        paymentsAmountSubtitle: amountSub,
        paymentsTransactionsSubtitle: transactionsSub,
        systemUptimeSubtitle: uptimeSub,
        systemSuccessRateSubtitle: successRateSub,
      });
    } catch (error) {
      console.error('[CardTitles] Error fetching from API:', error);
    }
  };

  // Fetch data from API
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [
          revenueRes,
          sharePriceRes,
          trendsRes,
          proportionsRes,
          postsRes,
          crossBorderRes,
          employeesRes,
          paymentsRes,
          systemRes,
          newsroomRes,
          resourcesRes,
        ] = await Promise.allSettled([
          dashboardApi.getRevenue(),
          dashboardApi.getSharePrice(),
          dashboardApi.getRevenueTrends(),
          dashboardApi.getRevenueProportions(),
          dashboardApi.getPosts(10),
          dashboardApi.getCrossBorderPosts(10),
          dashboardApi.getEmployees(20),
          dashboardApi.getPayments(),
          dashboardApi.getSystemPerformance(),
          dashboardApi.getNewsroom(12),
          dashboardApi.getResourcesNewsroom(8),
        ]);

        if (revenueRes.status === 'fulfilled') {
          console.log('[Initial Load] Revenue response:', revenueRes.value);
          console.log('[Initial Load] Revenue data from API:', revenueRes.value.data);
          const revenueData = revenueRes.value.data || {};
          const newRevenue = {
            total_amount: Number(revenueData.total_amount) || 0,
            percentage_change: Number(revenueData.percentage_change) || 0
          };
          console.log('[Initial Load] Setting revenue state to:', newRevenue);
          console.log('[Initial Load] Will display as:', `$${(newRevenue.total_amount / 1000000).toFixed(0)}M`);
          setRevenue(newRevenue);
          // Save to localStorage as backup
          localStorage.setItem('revenueData', JSON.stringify(newRevenue));
        } else {
          console.warn('[Initial Load] Revenue API failed:', revenueRes.reason);
          console.warn('[Initial Load] Full error:', revenueRes);
          // Fallback to localStorage if API fails
          const localRevenue = localStorage.getItem('revenueData');
          if (localRevenue) {
            try {
              const parsed = JSON.parse(localRevenue);
              setRevenue({
                total_amount: parsed.total_amount,
                percentage_change: parsed.percentage_change
              });
            } catch (e) {
              console.error('Failed to parse local revenue data:', e);
            }
          }
        }
        if (sharePriceRes.status === 'fulfilled') {
          console.log('[Initial Load] Share price data from API:', sharePriceRes.value.data);
          const sharePriceData = sharePriceRes.value.data || {};
          setSharePrice({
            price: Number(sharePriceData.price) || 0,
            change_percentage: Number(sharePriceData.change_percentage) || 0
          });
        } else {
          console.warn('[Initial Load] Share price API failed:', sharePriceRes.reason);
          // Fallback to localStorage if API fails
          const localSharePrice = localStorage.getItem('sharePriceData');
          if (localSharePrice) {
            try {
              const parsed = JSON.parse(localSharePrice);
              setSharePrice({
                price: parsed.price || 0,
                change_percentage: parsed.change_percentage || 0
              });
            } catch (e) {
              console.error('Failed to parse local share price data:', e);
            }
          }
        }
        if (trendsRes.status === 'fulfilled') {
          setRevenueTrends(trendsRes.value.data);
        }
        if (proportionsRes.status === 'fulfilled') {
          setRevenueProportions(proportionsRes.value.data);
        }
        if (postsRes.status === 'fulfilled') {
          const postsData = postsRes.value.data || [];
          const transformedPosts = postsData.map((post: any) => ({
            author: post.author || 'Corpay',
            timeAgo: post.time_ago || 'Just now',
            content: post.content || '',
            image: post.image_url || undefined,
            likes: post.likes || 0,
            comments: post.comments || 0,
            postUrl: post.post_url || undefined
          }));
          setPosts(transformedPosts);
        }
        if (crossBorderRes.status === 'fulfilled') {
          const crossBorderData = crossBorderRes.value.data || [];
          const transformedCrossBorder = crossBorderData.map((post: any) => ({
            author: post.author || 'Corpay Cross-Border',
            timeAgo: post.time_ago || 'Just now',
            content: post.content || '',
            image: post.image_url || undefined,
            likes: post.likes || 0,
            comments: post.comments || 0,
            postUrl: post.post_url || undefined
          }));
          setCrossBorderPostsList(transformedCrossBorder);
        }
        if (employeesRes.status === 'fulfilled') {
          const res = employeesRes.value;
          const raw = res?.data;
          const employeesData: any[] = Array.isArray(raw)
            ? raw
            : (raw && Array.isArray((raw as any).data)
              ? (raw as any).data
              : (raw && Array.isArray((raw as any).milestones) ? (raw as any).milestones : []));
          const MILESTONE_EMOJI: Record<string, string> = {
            anniversary: '📅',
            promotion: '📈',
            birthday: '🎂',
            new_hire: '✨',
            achievement: '🏆'
          };
          const transformedMilestones = employeesData.map((emp: any) => {
            // Milestone photos: prepend Supabase Storage bucket public URL to filename from DB
            let avatarUrl = 'https://via.placeholder.com/100';
            if (emp?.avatar_path) {
              const path = String(emp.avatar_path);
              if (path.startsWith('http://') || path.startsWith('https://')) {
                avatarUrl = path;
              } else {
                const bucketPublicUrl = import.meta.env.VITE_SUPABASE_STORAGE_PUBLIC_URL;
                if (bucketPublicUrl && String(bucketPublicUrl).trim()) {
                  avatarUrl = `${String(bucketPublicUrl).replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;
                } else {
                  const base = apiBaseURL.replace(/\/api\/?$/, '') || 'http://localhost:8080';
                  avatarUrl = `${String(base).replace(/\/+$/, '')}/uploads/${path.replace(/^\/+/, '')}`;
                }
              }
            }
            return {
              name: emp?.name ?? '',
              description: emp?.description ?? '',
              avatar: avatarUrl,
              borderColor: emp?.border_color || '#981239',
              backgroundColor: emp?.background_color || '#fef5f8',
              emoji: MILESTONE_EMOJI[emp?.milestone_type] || '🎉'
            };
          });
          setMilestonesList(transformedMilestones);
        } else {
          console.warn('[Initial Load] Employees API failed:', employeesRes.reason);
          setMilestonesList([]);
        }
        if (paymentsRes.status === 'fulfilled') {
          console.log('[Initial Load] Payments data from API:', paymentsRes.value.data);
          const paymentsData = paymentsRes.value.data || {};
          setPayments({
            amount_processed: Number(paymentsData.amount_processed) || 428000000,
            transaction_count: Number(paymentsData.transaction_count) || 19320
          });
        } else {
          console.warn('[Initial Load] Payments API failed:', paymentsRes.reason);
        }
        if (systemRes.status === 'fulfilled') {
          console.log('[Initial Load] System performance data from API:', systemRes.value.data);
          const systemData = systemRes.value.data || {};
          setSystemPerformance({
            uptime_percentage: Number(systemData.uptime_percentage) || 99.985,
            success_rate: Number(systemData.success_rate) || 99.62
          });
        } else {
          console.warn('[Initial Load] System performance API failed:', systemRes.reason);
        }
        if (newsroomRes.status === 'fulfilled') {
          setNewsroomItems(newsroomRes.value.data || []);
        }
        if (resourcesRes.status === 'fulfilled') {
          const data = resourcesRes.value.data;
          const list = Array.isArray(data) ? data : [];
          setResourceItems((prev) => (list.length > 0 ? list : prev));
        }
      } catch (error) {
        console.error('Error fetching dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    fetchCardTitles();

    // Refresh card titles every 60s
    const cardTitlesInterval = setInterval(fetchCardTitles, 60000);
    
    // Refresh data every 5 minutes
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    
    // Refresh revenue data every 30 seconds
    const revenueInterval = setInterval(() => {
      fetchRevenueData();
    }, 30000);
    
    // Function to fetch share price data
    const fetchSharePriceData = async () => {
      try {
        console.log('[SharePrice] Fetching from API...');
        const sharePriceRes = await dashboardApi.getSharePrice();
        console.log('[SharePrice] Full API Response:', sharePriceRes);
        console.log('[SharePrice] Response status:', sharePriceRes.status);
        console.log('[SharePrice] Response data:', sharePriceRes.data);
        
        // Axios wraps the response, so the actual data is in sharePriceRes.data
        const responseData = sharePriceRes.data;
        if (responseData) {
          console.log('[SharePrice] Parsed Response Data:', responseData);
          const newSharePrice = {
            price: Number(responseData.price) || 0,
            change_percentage: Number(responseData.change_percentage) || 0
          };
          console.log('[SharePrice] Setting state to:', newSharePrice);
          setSharePrice(newSharePrice);
          // Also save to localStorage as backup
          localStorage.setItem('sharePriceData', JSON.stringify(newSharePrice));
        } else {
          console.warn('[SharePrice] No data in API response:', sharePriceRes);
        }
      } catch (error) {
        console.error('[SharePrice] Error fetching from API:', error);
        // Fallback to localStorage if API fails
        const localSharePrice = localStorage.getItem('sharePriceData');
        if (localSharePrice) {
          try {
            const parsed = JSON.parse(localSharePrice);
            console.log('[SharePrice] Using localStorage data:', parsed);
            setSharePrice({
              price: parsed.price || 0,
              change_percentage: parsed.change_percentage || 0
            });
          } catch (e) {
            console.error('[SharePrice] Failed to parse localStorage:', e);
          }
        }
      }
    };
    
    // Store function reference for manual refresh
    fetchSharePriceDataRef.current = fetchSharePriceData;
    
    // Immediately fetch share price data on mount
    fetchSharePriceData();
    
    // Refresh share price data every 30 seconds
    const sharePriceInterval = setInterval(() => {
      fetchSharePriceData();
    }, 30000);

    // Function to fetch payments data
    const fetchPaymentsData = async () => {
      try {
        console.log('[Payments] Fetching from API...');
        const paymentsRes = await dashboardApi.getPayments();
        console.log('[Payments] API Response:', paymentsRes);
        const paymentsData = paymentsRes.data || {};
        const newPayments = {
          amount_processed: Number(paymentsData.amount_processed) || 428000000,
          transaction_count: Number(paymentsData.transaction_count) || 19320
        };
        console.log('[Payments] Setting state to:', newPayments);
        setPayments(newPayments);
      } catch (error) {
        console.error('[Payments] Error fetching from API:', error);
      }
    };

    // Function to fetch system performance data
    const fetchSystemPerformanceData = async () => {
      try {
        console.log('[SystemPerformance] Fetching from API...');
        const systemRes = await dashboardApi.getSystemPerformance();
        console.log('[SystemPerformance] API Response:', systemRes);
        const systemData = systemRes.data || {};
        const newSystemPerformance = {
          uptime_percentage: Number(systemData.uptime_percentage) || 99.985,
          success_rate: Number(systemData.success_rate) || 99.62
        };
        console.log('[SystemPerformance] Setting state to:', newSystemPerformance);
        setSystemPerformance(newSystemPerformance);
      } catch (error) {
        console.error('[SystemPerformance] Error fetching from API:', error);
      }
    };

    // Immediately fetch payments and system performance data on mount
    fetchPaymentsData();
    fetchSystemPerformanceData();

    // Refresh payments and system performance data every 30 seconds
    const paymentsInterval = setInterval(() => {
      fetchPaymentsData();
    }, 30000);

    const systemPerformanceInterval = setInterval(() => {
      fetchSystemPerformanceData();
    }, 30000);
    
    // Listen for manual refresh event
    const handleRefreshSharePrice = () => {
      fetchSharePriceData();
    };
    window.addEventListener('refreshSharePrice', handleRefreshSharePrice);
    
    // Listen for storage events (when admin dashboard saves to localStorage from different origin)
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'revenueData' && e.newValue) {
        try {
          const parsed = JSON.parse(e.newValue);
          console.log('Revenue updated from storage event:', parsed);
          setRevenue({
            total_amount: parsed.total_amount,
            percentage_change: parsed.percentage_change
          });
        } catch (error) {
          console.error('Failed to parse revenue data from storage event:', error);
        }
      }
      if (e.key === 'sharePriceData' && e.newValue) {
        try {
          const parsed = JSON.parse(e.newValue);
          console.log('Share price updated from storage event:', parsed);
          setSharePrice({
            price: parsed.price || 0,
            change_percentage: parsed.change_percentage || 0
          });
        } catch (error) {
          console.error('Failed to parse share price data from storage event:', error);
        }
      }
      if (e.key === 'chartProportions' && e.newValue) {
        try {
          const parsed = JSON.parse(e.newValue);
          console.log('Chart proportions updated from storage event:', parsed);
          setRevenueProportions(parsed);
        } catch (error) {
          console.error('Failed to parse chart proportions data from storage event:', error);
        }
      }
      if (e.key === 'revenueTrends' && e.newValue) {
        try {
          const parsed = JSON.parse(e.newValue);
          console.log('Revenue trends updated from storage event:', parsed);
          setRevenueTrends(parsed);
        } catch (error) {
          console.error('Failed to parse revenue trends data from storage event:', error);
        }
      }
    };
    
    // Listen for custom events (for same-origin or cross-origin communication)
    const handleRevenueUpdate = (e: CustomEvent) => {
      if (e.detail) {
        console.log('Revenue updated from custom event:', e.detail);
        setRevenue({
          total_amount: e.detail.total_amount,
          percentage_change: e.detail.percentage_change
        });
        // Also trigger immediate API fetch to get latest from backend
        fetchRevenueData();
      }
    };
    
    const handleSharePriceUpdate = (e: CustomEvent) => {
      if (e.detail) {
        console.log('Share price updated from custom event:', e.detail);
        setSharePrice({
          price: e.detail.price || 0,
          change_percentage: e.detail.change_percentage || 0
        });
        // Also trigger immediate API fetch to get latest from backend
        fetchSharePriceData();
      }
    };
    
    const handleChartProportionsUpdate = (e: CustomEvent) => {
      if (e.detail) {
        console.log('Chart proportions updated from custom event:', e.detail);
        setRevenueProportions(e.detail);
        // Also fetch from API to ensure consistency
        dashboardApi.getRevenueProportions()
          .then((response) => {
            if (response.data) {
              setRevenueProportions(response.data);
            }
          })
          .catch((error) => {
            console.error('Failed to fetch proportions from API:', error);
          });
      }
    };
    
    // Function to fetch revenue proportions data
    const fetchRevenueProportionsData = async () => {
      try {
        const proportionsRes = await dashboardApi.getRevenueProportions();
        if (proportionsRes && proportionsRes.data) {
          setRevenueProportions(proportionsRes.data);
          localStorage.setItem('chartProportions', JSON.stringify(proportionsRes.data));
        }
      } catch (error) {
        console.error('Error fetching revenue proportions:', error);
        // Fallback to localStorage
        const localProportions = localStorage.getItem('chartProportions');
        if (localProportions) {
          try {
            const parsed = JSON.parse(localProportions);
            setRevenueProportions(parsed);
          } catch (e) {
            console.error('Failed to parse local proportions data:', e);
          }
        }
      }
    };

    const handleRevenueTrendsUpdate = (e: CustomEvent) => {
      if (e.detail) {
        console.log('Revenue trends updated from custom event:', e.detail);
        setRevenueTrends(e.detail);
        // Also fetch from API to ensure consistency
        dashboardApi.getRevenueTrends()
          .then((response) => {
            if (response.data) {
              setRevenueTrends(response.data);
            }
          })
          .catch((error) => {
            console.error('Failed to fetch revenue trends from API:', error);
          });
      }
    };
    
    // Refresh proportions every 30 seconds
    const proportionsInterval = setInterval(() => {
      fetchRevenueProportionsData();
    }, 30000);
    
    // Function to fetch employee milestones data
    const fetchEmployeesData = async () => {
      try {
        const employeesRes = await dashboardApi.getEmployees(20);
        if (employeesRes && employeesRes.data !== undefined) {
          const raw = employeesRes.data;
          const employeesData: any[] = Array.isArray(raw)
            ? raw
            : (raw && Array.isArray((raw as any).data) ? (raw as any).data : (raw && Array.isArray((raw as any).milestones) ? (raw as any).milestones : []));
          const MILESTONE_EMOJI: Record<string, string> = {
            anniversary: '📅',
            promotion: '📈',
            birthday: '🎂',
            new_hire: '✨',
            achievement: '🏆'
          };
          const transformedMilestones = employeesData.map((emp: any) => {
            // Milestone photos: prepend Supabase Storage bucket public URL to filename from DB
            let avatarUrl = 'https://via.placeholder.com/100';
            if (emp?.avatar_path) {
              const path = String(emp.avatar_path);
              if (path.startsWith('http://') || path.startsWith('https://')) {
                avatarUrl = path;
              } else {
                const bucketPublicUrl = import.meta.env.VITE_SUPABASE_STORAGE_PUBLIC_URL;
                if (bucketPublicUrl && String(bucketPublicUrl).trim()) {
                  avatarUrl = `${String(bucketPublicUrl).replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;
                } else {
                  const base = apiBaseURL.replace(/\/api\/?$/, '') || 'http://localhost:8080';
                  avatarUrl = `${String(base).replace(/\/+$/, '')}/uploads/${path.replace(/^\/+/, '')}`;
                }
              }
            }
            return {
              name: emp?.name ?? '',
              description: emp?.description ?? '',
              avatar: avatarUrl,
              borderColor: emp?.border_color || '#981239',
              backgroundColor: emp?.background_color || '#fef5f8',
              emoji: MILESTONE_EMOJI[emp?.milestone_type] || '🎉'
            };
          });
          setMilestonesList(transformedMilestones);
        }
      } catch (error) {
        console.error('Error fetching employee milestones:', error);
      }
    };
    
    // Fetch employee milestones immediately and then every 30 seconds
    fetchEmployeesData();
    const employeesInterval = setInterval(() => {
      fetchEmployeesData();
    }, 30000);
    
    window.addEventListener('storage', handleStorageChange);
    window.addEventListener('revenueDataUpdated', handleRevenueUpdate as EventListener);
    window.addEventListener('sharePriceDataUpdated', handleSharePriceUpdate as EventListener);
    window.addEventListener('chartProportionsUpdated', handleChartProportionsUpdate as EventListener);
    window.addEventListener('revenueTrendsUpdated', handleRevenueTrendsUpdate as EventListener);
    
    // Function to fetch slideshow state (supports file_url for PDFs and embed_url/source for Power BI)
    const fetchSlideshowState = async () => {
      try {
        const base = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';
        const response = await axios.get(`${base}/dashboard/slideshow`, { timeout: 120000 });
        if (response.data) {
          const slideshowType: 'file' | 'url' = response.data.type === 'url' ? 'url' : 'file';
          const source = response.data.source || null;
          const fileUrl = response.data.file_url || (slideshowType === 'file' ? source : null);
          const embedUrl = slideshowType === 'url' ? source : null;
          const newState = {
            is_active: Boolean(response.data.is_active),
            type: slideshowType,
            file_url: fileUrl,
            embed_url: embedUrl,
            file_name: response.data.file_name || null,
            interval_seconds: response.data.interval_seconds ?? 5,
          };
          setSlideshowState(prev => {
            const prevSource = prev.type === 'url' ? prev.embed_url : prev.file_url;
            const nextSource = newState.type === 'url' ? newState.embed_url : newState.file_url;
            const changed =
              prev.is_active !== newState.is_active ||
              prev.type !== newState.type ||
              prevSource !== nextSource ||
              prev.interval_seconds !== newState.interval_seconds;
            if (changed) {
              console.log('[App] Slideshow state changed:', {
                is_active: newState.is_active,
                type: newState.type,
                file_url: newState.file_url,
                embed_url: newState.embed_url,
                interval_seconds: newState.interval_seconds,
              });
            }
            return newState;
          });
        }
      } catch (error) {
        // Don't deactivate slideshow on API error - keep current state
        console.debug('[App] Slideshow state check failed (keeping current state):', error);
      }
    };
    
    // Poll slideshow state every 5s
    fetchSlideshowState();
    const slideshowInterval = setInterval(fetchSlideshowState, 5000);
    
    return () => {
      clearInterval(interval);
      clearInterval(cardTitlesInterval);
      clearInterval(revenueInterval);
      clearInterval(sharePriceInterval);
      clearInterval(proportionsInterval);
      clearInterval(employeesInterval);
      clearInterval(slideshowInterval);
      clearInterval(paymentsInterval);
      clearInterval(systemPerformanceInterval);
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('revenueDataUpdated', handleRevenueUpdate as EventListener);
      window.removeEventListener('sharePriceDataUpdated', handleSharePriceUpdate as EventListener);
      window.removeEventListener('chartProportionsUpdated', handleChartProportionsUpdate as EventListener);
      window.removeEventListener('refreshSharePrice', handleRefreshSharePrice);
      window.removeEventListener('revenueTrendsUpdated', handleRevenueTrendsUpdate as EventListener);
    };
  }, []);

  // When slideshow becomes active, fetch state immediately so interval_seconds is correct before first slide (avoids first page holding for wrong interval)
  useEffect(() => {
    if (!slideshowState.is_active) return;
    const base = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';
    axios.get(`${base}/dashboard/slideshow`, { timeout: 120000 }).then((response) => {
      if (!response?.data) return;
      const slideshowType = response.data.type === 'url' ? 'url' : 'file';
      const source = response.data.source || null;
      const fileUrl = response.data.file_url || (slideshowType === 'file' ? source : null);
      const embedUrl = slideshowType === 'url' ? source : null;
      setSlideshowState({
        is_active: true,
        type: slideshowType,
        file_url: fileUrl,
        embed_url: embedUrl,
        file_name: response.data.file_name || null,
        interval_seconds: response.data.interval_seconds ?? 5,
      });
    }).catch(() => {});
  }, [slideshowState.is_active]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    let scrollInterval: NodeJS.Timeout;
    let addPostInterval: NodeJS.Timeout;

    // Auto scroll
    scrollInterval = setInterval(() => {
      if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
        container.scrollTop = 0;
      } else {
        container.scrollTop += 1;
      }
    }, 40);

    // Add new posts periodically (pick from current list if any)
    addPostInterval = setInterval(() => {
      setPosts(prev => {
        if (prev.length === 0) return prev;
        const newPost = prev[Math.floor(Math.random() * prev.length)];
        return [...prev, { ...newPost, timeAgo: 'Just now' }];
      });
    }, 5000);

    return () => {
      clearInterval(scrollInterval);
      clearInterval(addPostInterval);
    };
  }, []);

  useEffect(() => {
    const container = scrollContainerRef2.current;
    if (!container) return;

    let scrollInterval: NodeJS.Timeout;
    let addPostInterval: NodeJS.Timeout;

    // Auto scroll
    scrollInterval = setInterval(() => {
      if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
        container.scrollTop = 0;
      } else {
        container.scrollTop += 1;
      }
    }, 40);

    // Add new posts periodically (pick from current list if any)
    addPostInterval = setInterval(() => {
      setCrossBorderPostsList(prev => {
        if (prev.length === 0) return prev;
        const newPost = prev[Math.floor(Math.random() * prev.length)];
        return [...prev, { ...newPost, timeAgo: 'Just now' }];
      });
    }, 5000);

    return () => {
      clearInterval(scrollInterval);
      clearInterval(addPostInterval);
    };
  }, []);

  useEffect(() => {
    const container = milestonesScrollRef.current;
    if (!container) return;

    let scrollInterval: NodeJS.Timeout;

    // Auto scroll vertically
    scrollInterval = setInterval(() => {
      if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
        container.scrollTop = 0;
      } else {
        container.scrollTop += 1;
      }
    }, 40);

    // Employee milestones are now fetched from API only - no auto-adding

    return () => {
      clearInterval(scrollInterval);
    };
  }, []);

  // Resources auto-scroll (same as LinkedIn posts) - start after paint so ref and scrollHeight are set
  useEffect(() => {
    const rafId = requestAnimationFrame(() => {
      const container = resourcesScrollRef.current;
      if (!container || container.scrollHeight <= container.clientHeight) return;
      resourcesScrollIntervalRef.current = setInterval(() => {
        if (!container) return;
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
          container.scrollTop = 0;
        } else {
          container.scrollTop += 1;
        }
      }, 40);
    });
    return () => {
      cancelAnimationFrame(rafId);
      if (resourcesScrollIntervalRef.current) {
        clearInterval(resourcesScrollIntervalRef.current);
        resourcesScrollIntervalRef.current = null;
      }
    };
  }, [resourceItems.length]);

  // Newsroom auto-scroll (same as Resources) - start after paint
  useEffect(() => {
    const rafId = requestAnimationFrame(() => {
      const container = newsroomScrollRef.current;
      if (!container || container.scrollHeight <= container.clientHeight) return;
      newsroomScrollIntervalRef.current = setInterval(() => {
        if (!container) return;
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
          container.scrollTop = 0;
        } else {
          container.scrollTop += 1;
        }
      }, 40);
    });
    return () => {
      cancelAnimationFrame(rafId);
      if (newsroomScrollIntervalRef.current) {
        clearInterval(newsroomScrollIntervalRef.current);
        newsroomScrollIntervalRef.current = null;
      }
    };
  }, [newsroomItems.length]);

  // If slideshow is active, show only the slideshow (PDF/file or Power BI URL)
  const slideshowSource =
    slideshowState.type === 'url' ? slideshowState.embed_url : slideshowState.file_url;
  if (slideshowState.is_active && slideshowSource) {
    console.log('[App] Rendering slideshow - Active:', slideshowState.is_active, 'type:', slideshowState.type, 'source:', slideshowSource);
    return (
      <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 99999, backgroundColor: '#000' }}>
        <FullScreenSlideshow 
          slideshowType={slideshowState.type}
          source={slideshowSource}
          intervalSeconds={slideshowState.interval_seconds ?? 5}
          onClose={async () => {
            try {
              const { apiBaseURL } = await import('./services/api');
              await axios.post(`${apiBaseURL}/admin/slideshow/stop-dev`);
            } catch (error) {
              console.error('Failed to stop slideshow from frontend:', error);
            }
            setSlideshowState({
              is_active: false,
              type: 'file',
              file_url: null,
              embed_url: null,
              file_name: null,
              interval_seconds: 5,
            });
          }}
        />
      </div>
    );
  }

  return (
    <div className="min-h-full w-full p-8 box-border" style={{ 
      backgroundImage: `url(${backgroundPattern})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundRepeat: 'no-repeat',
      backgroundAttachment: 'fixed',
      backgroundColor: '#f5f5f5'
    }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <img src={corpayLogo} alt="Corpay" className="h-10 brightness-0 invert" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Content - 3 columns */}
        <div className="lg:col-span-3 space-y-6">
          {isFrontendPowerBI && powerBIEmbedUrl ? (
            <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 flex flex-col" style={{ minHeight: '680px' }}>
              <p className="mb-4" style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>Power BI Dashboard</p>
              <div className="flex-1 rounded-lg overflow-hidden border border-gray-100" style={{ minHeight: '620px', position: 'relative' }}>
                <iframe
                  src={powerBIEmbedUrl}
                  title="Power BI Dashboard"
                  style={{ 
                    width: '100%', 
                    height: '100%', 
                    border: '0',
                    display: 'block',
                    position: 'absolute',
                    top: 0,
                    left: 0
                  }}
                  allowFullScreen
                />
              </div>
            </div>
          ) : (
            <>
              {/* Top Row - Metrics */}
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                {/* Total Revenue and Share Price - Stacked */}
                <div className="md:col-span-1 flex flex-col gap-4">
                  {/* Total Revenue - Half height */}
                  <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-xs text-gray-500">Total Revenue</p>
                    </div>
                    <p style={{ fontWeight: 700, color: 'rgb(152, 18, 57)', fontSize: '28px', lineHeight: '1', marginBottom: '4px' }}>
                      ${revenue.total_amount > 0 ? (revenue.total_amount / 1000000).toFixed(0) : '0'}M
                    </p>
                    <p className="text-xs" style={{ color: '#0085C2', fontWeight: 600 }}>
                      ▲ {revenue.percentage_change.toFixed(1)}% vs last quarter
                    </p>
                  </div>

                  {/* Share Price - Fills remaining space */}
                  <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 flex-1 flex flex-col justify-center">
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-xs text-gray-500">Corpay Share Price</p>
                    </div>
                    <p style={{ fontWeight: 700, color: '#230C18', fontSize: '28px', lineHeight: '1', marginBottom: '8px' }}>
                      $ {sharePrice.price > 0 ? sharePrice.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}
                    </p>
                    <div className="flex items-center gap-1">
                      <span style={{ color: '#0085C2', fontSize: '16px', fontWeight: 600 }}>
                        {(() => {
                          const change = parseFloat(String(sharePrice.change_percentage || 0));
                          return change >= 0 ? '▲' : '▼';
                        })()} {sharePrice.change_percentage >= 0 ? '+' : ''}{sharePrice.change_percentage.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </div>

                {/* Revenue Proportions */}
                <div className="md:col-span-2 bg-white p-6 rounded-lg shadow-sm border border-gray-100">
                  <p className="mb-4" style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>Revenue Proportions</p>
                    <div className="flex items-center justify-between gap-6 px-4">
                    <ResponsiveContainer width={130} height={130}>
                      <PieChart>
                        <Pie
                          data={revenueProportions}
                          cx={65}
                          cy={65}
                          innerRadius={40}
                          outerRadius={60}
                          paddingAngle={3}
                          dataKey="percentage"
                        >
                          {revenueProportions.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 flex-1">
                      {revenueProportions.map((item) => (
                        <div key={item.category} className="flex items-center justify-between gap-3 p-2 rounded" style={{ backgroundColor: '#fafafa' }}>
                          <div className="flex items-center gap-2">
                            <div className="w-4 h-4 rounded" style={{ backgroundColor: item.color }}></div>
                            <span className="text-sm" style={{ color: '#3D1628', fontWeight: 600 }}>{item.category}</span>
                          </div>
                          <span style={{ color: '#3D1628', fontWeight: 700, fontSize: '15px' }}>{item.percentage}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Revenue Trend */}
                <div className="md:col-span-2 bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col">
                    <div className="flex items-center justify-between mb-4">
                    <p style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>Revenue Trends</p>
                    <div className="flex items-center gap-2">
                      <div className="px-3 py-1.5 rounded-full" style={{ background: 'linear-gradient(135deg, #981239 0%, #BE1549 100%)', color: 'white', fontSize: '13px', fontWeight: 700 }}>
                        ${(revenue.total_amount / 1000000).toFixed(0)}M
                      </div>
                    </div>
                  </div>
                  <div className="flex-1 flex items-center justify-center px-2">
                    <ResponsiveContainer width="95%" height={100}>
                      <BarChart data={revenueTrends} margin={{ top: 5, right: 5, left: -10, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                        <XAxis 
                          dataKey="month" 
                          tick={{ fontSize: 10, fill: '#3D1628', fontWeight: 600 }}
                          axisLine={{ strokeWidth: 2, stroke: '#3D1628' }}
                          tickLine={false}
                        />
                        <YAxis 
                          tick={{ fontSize: 10, fill: '#3D1628', fontWeight: 600 }}
                          axisLine={{ strokeWidth: 2, stroke: '#3D1628' }}
                          tickLine={false}
                          // Auto‑scale from 0 up to the maximum
                          // value coming from the Excel / API data
                          domain={[0, 'dataMax']}
                        />
                        <Bar
                          dataKey="value"
                          radius={[4, 4, 0, 0]}
                          shape={(props: any) => {
                            const { x, y, width, height, payload } = props;
                            const month = payload.month;
                            const rank = topThreeMonthsByValue.indexOf(month);

                            // Corpay color palette for top 3 bars
                            let fillColor = '#E6E8E7'; // default
                            if (rank === 0) {
                              fillColor = '#981239'; // deep Corpay pink - highest
                            } else if (rank === 1) {
                              fillColor = '#3D1628'; // dark Corpay plum - second highest
                            } else if (rank === 2) {
                              fillColor = '#BE1549'; // lighter Corpay pink - third highest
                            }

                            return (
                              <rect
                                x={x}
                                y={y}
                                width={width}
                                height={height}
                                fill={fillColor}
                                rx={4}
                                ry={4}
                              />
                            );
                          }}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* Second Row */}
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                {/* Employee Milestones */}
                <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col md:col-span-3" style={{ height: '400px' }}>
                  <p className="mb-4" style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>Employee Milestones</p>
                  <div ref={milestonesScrollRef} className="overflow-y-auto flex-1 space-y-3 scrollbar-hide" style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
                    {milestonesList.map((milestone, index) => (
                      <EmployeeMilestone 
                        key={index}
                        name={milestone.name}
                        description={milestone.description}
                        avatar={milestone.avatar}
                        borderColor={milestone.borderColor}
                        backgroundColor={milestone.backgroundColor}
                        emoji={milestone.emoji}
                      />
                    ))}
                  </div>
                </div>

                {/* Right Column - Stacked Boxes */}
                <div className="md:col-span-2 space-y-4" style={{ height: '400px' }}>
                {/* Payments Processed Today */}
                  <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col" style={{ height: '192px' }}>
                    <div className="flex items-center justify-between mb-4">
                      <p style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>{cardTitles.payments}</p>
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: '#0085C2' }}></div>
                    </div>
                    <div className="flex items-center justify-center flex-1 gap-8">
                      {/* Grey text above value = Subtitle 1 (from admin); value = amount in Cr */}
                      <div className="text-center space-y-2 flex-1">
                        <p className="text-gray-500" style={{ fontSize: '11px', fontWeight: 500 }}>{cardTitles.paymentsAmountSubtitle}</p>
                        <p style={{ fontWeight: 700, color: 'rgb(152, 18, 57)', fontSize: '32px', lineHeight: '1' }}>
                          {(payments.amount_processed / 10000000).toFixed(1)}
                        </p>
                      </div>

                      {/* Vertical Divider */}
                      <div className="w-px h-16" style={{ backgroundColor: '#E6E8E7' }}></div>

                      {/* Grey text above value = Subtitle 2 (from admin); value = transaction count */}
                      <div className="text-center space-y-2 flex-1">
                        <p className="text-gray-500" style={{ fontSize: '11px', fontWeight: 500 }}>{cardTitles.paymentsTransactionsSubtitle}</p>
                        <p style={{ fontWeight: 700, color: '#230C18', fontSize: '32px', lineHeight: '1' }}>
                          {payments.transaction_count.toLocaleString()}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* System Performance / Uptime */}
                  <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col" style={{ height: '192px' }}>
                    <div className="flex items-center justify-between mb-4">
                      <p style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>{cardTitles.systemPerformance}</p>
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: '#0085C2' }}></div>
                    </div>
                    <div className="flex items-center justify-center flex-1 gap-8">
                      <div className="text-center space-y-2 flex-1">
                        <p className="text-gray-500" style={{ fontSize: '11px', fontWeight: 500 }}>{cardTitles.systemUptimeSubtitle}</p>
                        <p style={{ fontWeight: 700, color: '#230C18', fontSize: '32px', lineHeight: '1' }}>
                          {systemPerformance.uptime_percentage.toFixed(3)}
                        </p>
                      </div>

                      {/* Vertical Divider */}
                      <div className="w-px h-16" style={{ backgroundColor: '#E6E8E7' }}></div>

                      <div className="text-center space-y-2 flex-1">
                        <p className="text-gray-500" style={{ fontSize: '11px', fontWeight: 500 }}>{cardTitles.systemSuccessRateSubtitle}</p>
                        <p style={{ fontWeight: 700, color: '#981239', fontSize: '32px', lineHeight: '1' }}>
                          {systemPerformance.success_rate.toFixed(2)}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Third Row - Fixed row height so Newsroom matches Resources column; list scrolls inside */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-stretch min-h-0" style={{ height: '420px' }}>
            {/* Corpay Newsroom - fills row height; list scrolls inside */}
            <div className="min-h-0 flex flex-col h-full overflow-hidden">
              <div
                className="p-6 rounded-lg flex flex-col overflow-hidden flex-1 min-h-0 h-full"
                style={{
                  background: 'linear-gradient(180deg, #fef6f8 0%, #ffffff 100%)',
                  boxShadow: '0 2px 12px rgba(152, 18, 57, 0.08)',
                  border: '1px solid rgba(152, 18, 57, 0.15)',
                }}
              >
                <div className="flex items-center gap-2 mb-4 shrink-0">
                  <div className="w-1 h-6 rounded-full" style={{ backgroundColor: '#981239' }} />
                  <p className="m-0" style={{ fontWeight: 700, color: '#981239', fontSize: '18px' }}>Corpay Newsroom</p>
                </div>
                <div
                  ref={newsroomScrollRef}
                  className="space-y-3 flex-1 min-h-0 overflow-y-auto scrollbar-hide pr-1"
                  style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                >
                {newsroomItems.map((item, index) => (
                  <CompanyAnnouncement
                    key={index}
                    title={item.title}
                    date={newsroomDisplayDate(item)}
                    description={item.excerpt || ''}
                    backgroundColor={index % 2 === 0 ? 'rgba(152, 18, 57, 0.08)' : 'rgba(61, 22, 40, 0.07)'}
                    link={item.url}
                    accentBorder
                    accentColor={index % 2 === 0 ? '#981239' : '#3D1628'}
                  />
                ))}
                {newsroomItems.length === 0 && (
                  <p className="text-sm" style={{ color: '#3D1628', opacity: 0.8 }}>
                    Latest Corpay newsroom items will appear here once available.
                  </p>
                )}
              </div>
              </div>
            </div>

            {/* Right column: Resources only - fills row height; scrolls inside */}
            <div className="min-h-0 flex flex-col h-full overflow-hidden">
              <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col overflow-hidden flex-1 min-h-0 h-full">
                <p className="mb-3 shrink-0" style={{ fontWeight: 700, color: '#3D1628', fontSize: '18px' }}>Resources</p>
                <div
                  ref={resourcesScrollRef}
                  className="overflow-y-auto overflow-x-hidden flex-1 min-h-0 rounded space-y-4 scrollbar-hide"
                  style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                >
                  {Array.isArray(resourceItems) && resourceItems.length > 0 ? (
                    resourceItems.slice(0, 8).map((item, index) => (
                      <ResourceCard
                        key={'id' in item && item.id != null ? String(item.id) : index}
                        title={item.title || 'Resource'}
                        description={item.excerpt || ''}
                        type={index % 2 === 0 ? 'case-study' : 'whitepaper'}
                        resourceId={undefined}
                        url={item.url && String(item.url).trim() ? item.url : undefined}
                      />
                    ))
                  ) : (
                    <p className="text-sm" style={{ color: '#6b7280' }}>Resources will appear here once fetched from the web.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* LinkedIn Posts Column - Auto Scrolling */}
        <div className="lg:col-span-1 flex flex-col gap-6">

          {/* Corpay Cross-Border Posts */}
          <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 flex flex-col" style={{ height: '600px' }}>
            <p className="mb-4" style={{ fontWeight: 700, color: '#981239', fontSize: '18px' }}>Corpay Cross-Border Posts</p>
            <div ref={scrollContainerRef2} className="overflow-y-auto scrollbar-hide flex-1" style={{ 
              scrollbarWidth: 'none', 
              msOverflowStyle: 'none'
            }}>
              {crossBorderPostsList.length === 0 ? (
                <p className="text-gray-500 text-sm py-6 text-center">Latest Corpay Cross-Border post will appear here once available</p>
              ) : (
                crossBorderPostsList.map((post, index) => (
                  <LinkedInPostCard 
                    key={index}
                    author={post.author}
                    timeAgo={post.timeAgo}
                    content={post.content}
                    image={post.image}
                    likes={post.likes || 0}
                    comments={post.comments || 0}
                    isCorpayBrand={true}
                    postUrl={post.postUrl}
                  />
                ))
              )}
            </div>
          </div>

          {/* Corpay Posts */}
          <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 flex flex-col" style={{ height: '512px' }}> 
            <p className="mb-4" style={{ fontWeight: 700, color: '#981239', fontSize: '18px' }}>Corpay Posts</p> 
            <div ref={scrollContainerRef} className="overflow-y-auto scrollbar-hide flex-1" style={{ 
              scrollbarWidth: 'none', 
              msOverflowStyle: 'none'
            }}> 
              {posts.length === 0 ? (
                <p className="text-gray-500 text-sm py-6 text-center">Latest Corpay post will appear here once available</p>
              ) : (
                posts.map((post, index) => ( 
                  <LinkedInPostCard 
                    key={index} 
                    author={post.author} 
                    timeAgo={post.timeAgo} 
                    content={post.content} 
                    image={post.image}
                    likes={post.likes || 0}
                    comments={post.comments || 0}
                    postUrl={post.postUrl}
                  /> 
                ))
              )}
            </div> 
          </div>
        </div>
      </div>
    </div>
  );
}