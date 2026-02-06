import { registerAlpineComponent } from '../alpine-components';

interface DatePickerConfig {
    modelName?: string;
    initialValue?: string;
    onChange?: (value: string) => void;
    includeTime?: boolean;
    use24HourFormat?: boolean;
}

/**
 * Advanced Date/DateTime Picker Component
 * Features:
 * - Day selection view with calendar grid
 * - Month selection view (3x4 grid)
 * - Year selection view (3x4 grid with range navigation)
 * - Optional time selection (hour/minute with AM/PM toggle)
 * - Today/Now button and Clear button
 * - Highlights current date and selected date
 */
export function datePicker(config: DatePickerConfig = {}) {
    const { initialValue = '', onChange, includeTime = false, use24HourFormat = false } = config;

    const today = new Date();
    const initialDate = initialValue ? new Date(initialValue) : null;

    return {
        open: false,
        viewMode: 'days' as 'days' | 'months' | 'years',
        selectedValue: initialValue,
        currentMonth: initialDate?.getMonth() ?? today.getMonth(),
        currentYear: initialDate?.getFullYear() ?? today.getFullYear(),
        yearRangeStart: Math.floor((initialDate?.getFullYear() ?? today.getFullYear()) / 12) * 12,
        today: today,
        weekdays: ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'],
        months: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        monthsFull: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],

        // Time selection properties
        includeTime: includeTime,
        use24HourFormat: use24HourFormat,
        selectedHour: initialDate?.getHours() ?? today.getHours(),
        selectedMinute: initialDate?.getMinutes() ?? 0,
        isPM: (initialDate?.getHours() ?? today.getHours()) >= 12,

        get selectedDate(): Date | null {
            if (!this.selectedValue) return null;
            const d = new Date(this.selectedValue);
            return isNaN(d.getTime()) ? null : d;
        },

        get daysInMonth(): number {
            return new Date(this.currentYear, this.currentMonth + 1, 0).getDate();
        },

        get firstDayOfMonth(): number {
            return new Date(this.currentYear, this.currentMonth, 1).getDay();
        },

        get lastMonthDays(): number[] {
            const days: number[] = [];
            const prev = new Date(this.currentYear, this.currentMonth, 0).getDate();
            for (let i = this.firstDayOfMonth - 1; i >= 0; i--) {
                days.push(prev - i);
            }
            return days;
        },

        get currentMonthDays(): number[] {
            return Array.from({ length: this.daysInMonth }, (_, i) => i + 1);
        },

        get nextMonthDays(): number[] {
            const totalCells = 42;
            const remaining = totalCells - this.lastMonthDays.length - this.currentMonthDays.length;
            return Array.from({ length: remaining }, (_, i) => i + 1);
        },

        get yearRange(): number[] {
            return Array.from({ length: 12 }, (_, i) => this.yearRangeStart + i);
        },

        // Time-related computed properties
        get displayHour(): number {
            if (this.use24HourFormat) return this.selectedHour;
            const h = this.selectedHour % 12;
            return h === 0 ? 12 : h;
        },

        get hourOptions(): number[] {
            return this.use24HourFormat
                ? Array.from({ length: 24 }, (_, i) => i)
                : [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
        },

        get minuteOptions(): number[] {
            // 5-minute intervals for cleaner UI
            return Array.from({ length: 12 }, (_, i) => i * 5);
        },

        isToday(day: number): boolean {
            return day === this.today.getDate() &&
                this.currentMonth === this.today.getMonth() &&
                this.currentYear === this.today.getFullYear();
        },

        isSelected(day: number): boolean {
            if (!this.selectedDate) return false;
            return day === this.selectedDate.getDate() &&
                this.currentMonth === this.selectedDate.getMonth() &&
                this.currentYear === this.selectedDate.getFullYear();
        },

        isCurrentMonth(month: number): boolean {
            return month === this.today.getMonth() && this.currentYear === this.today.getFullYear();
        },

        isSelectedMonth(month: number): boolean {
            return this.selectedDate !== null &&
                month === this.selectedDate.getMonth() &&
                this.currentYear === this.selectedDate.getFullYear();
        },

        isCurrentYear(year: number): boolean {
            return year === this.today.getFullYear();
        },

        isSelectedYear(year: number): boolean {
            return this.selectedDate !== null && year === this.selectedDate.getFullYear();
        },

        selectDate(day: number): void {
            const d = new Date(this.currentYear, this.currentMonth, day);
            if (this.includeTime) {
                d.setHours(this.selectedHour, this.selectedMinute, 0, 0);
                this.selectedValue = this.formatDateTimeLocal(d);
            } else {
                this.selectedValue = d.toISOString().split('T')[0];
                this.open = false;
            }
            this.viewMode = 'days';
            if (onChange) onChange(this.selectedValue);
        },

        // Format date as YYYY-MM-DDTHH:mm (datetime-local compatible)
        formatDateTimeLocal(date: Date): string {
            const pad = (n: number) => n.toString().padStart(2, '0');
            return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
        },

        // Time selection methods
        setHour(hour: number): void {
            if (this.use24HourFormat) {
                this.selectedHour = hour;
            } else {
                // Convert 12-hour format to 24-hour
                if (this.isPM) {
                    this.selectedHour = hour === 12 ? 12 : hour + 12;
                } else {
                    this.selectedHour = hour === 12 ? 0 : hour;
                }
            }
            this.updateDateTime();
        },

        setMinute(minute: number): void {
            this.selectedMinute = minute;
            this.updateDateTime();
        },

        togglePeriod(): void {
            this.isPM = !this.isPM;
            this.selectedHour = (this.selectedHour + 12) % 24;
            this.updateDateTime();
        },

        updateDateTime(): void {
            if (this.selectedDate && this.includeTime) {
                const d = new Date(this.selectedDate);
                d.setHours(this.selectedHour, this.selectedMinute, 0, 0);
                this.selectedValue = this.formatDateTimeLocal(d);
                if (onChange) onChange(this.selectedValue);
            }
        },

        selectMonth(month: number): void {
            this.currentMonth = month;
            this.viewMode = 'days';
        },

        selectYear(year: number): void {
            this.currentYear = year;
            this.yearRangeStart = Math.floor(year / 12) * 12;
            this.viewMode = 'months';
        },

        prevMonth(): void {
            if (this.currentMonth === 0) {
                this.currentMonth = 11;
                this.currentYear--;
            } else {
                this.currentMonth--;
            }
        },

        nextMonth(): void {
            if (this.currentMonth === 11) {
                this.currentMonth = 0;
                this.currentYear++;
            } else {
                this.currentMonth++;
            }
        },

        prevYearRange(): void {
            this.yearRangeStart -= 12;
        },

        nextYearRange(): void {
            this.yearRangeStart += 12;
        },

        goToToday(): void {
            this.currentMonth = this.today.getMonth();
            this.currentYear = this.today.getFullYear();
            if (this.includeTime) {
                const d = new Date(this.today);
                d.setHours(this.selectedHour, this.selectedMinute, 0, 0);
                this.selectedValue = this.formatDateTimeLocal(d);
            } else {
                this.selectedValue = this.today.toISOString().split('T')[0];
                this.open = false;
            }
            this.viewMode = 'days';
            if (onChange) onChange(this.selectedValue);
        },

        goToNow(): void {
            const now = new Date();
            this.currentMonth = now.getMonth();
            this.currentYear = now.getFullYear();
            this.selectedHour = now.getHours();
            this.selectedMinute = now.getMinutes();
            this.isPM = now.getHours() >= 12;
            if (this.includeTime) {
                this.selectedValue = this.formatDateTimeLocal(now);
            } else {
                this.selectedValue = now.toISOString().split('T')[0];
            }
            this.open = false;
            this.viewMode = 'days';
            if (onChange) onChange(this.selectedValue);
        },

        clearDate(): void {
            this.selectedValue = '';
            this.viewMode = 'days';
            // Reset time to current time when clearing
            const now = new Date();
            this.selectedHour = now.getHours();
            this.selectedMinute = 0;
            this.isPM = now.getHours() >= 12;
            if (onChange) onChange('');
        },

        // Close the calendar (for datetime mode, can be called via Done button)
        confirmDateTime(): void {
            this.open = false;
            this.viewMode = 'days';
        },

        closeCalendar(): void {
            this.open = false;
            this.viewMode = 'days';
        },

        toggleCalendar(): void {
            this.open = !this.open;
        },

        formatDisplayDate(): string {
            if (!this.selectedValue) return '';
            const date = new Date(this.selectedValue);
            if (isNaN(date.getTime())) return this.selectedValue;

            const options: Intl.DateTimeFormatOptions = {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            };

            if (this.includeTime) {
                options.hour = 'numeric';
                options.minute = '2-digit';
                options.hour12 = !this.use24HourFormat;
            }

            return date.toLocaleString('en-US', options);
        },

        get calendarTitle(): string {
            return `${this.monthsFull[this.currentMonth]} ${this.currentYear}`;
        },

        get yearRangeTitle(): string {
            return `${this.yearRangeStart} - ${this.yearRangeStart + 11}`;
        }
    };
}

export function registerDatePicker(): void {
    registerAlpineComponent('datePicker', datePicker);
}

export default { datePicker, registerDatePicker };
