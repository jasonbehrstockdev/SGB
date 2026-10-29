
int flag_verbose=0, flag_full=0, flag_counter=0, flag_alpha=0, flag_debug=0, flag_export=0, flag_teaformatted=0, flag_smallworld=0;

if (argc>1 && argv[1][0] == '-')
{ 
    std::string flags_counter = argv[1];
    flag_counter=1;
    
    for (int i=1; i<flags_counter.length(); i++)
    {
//	cout << "argv[1][i]="<< argv[1][i] << "\n";

        switch (argv[1][i])
        { 
            case 'v':
                flag_verbose=1;
                break;
            case 'f':
                flag_full=1;
                break;
            case 'd':
                flag_debug=1;
                break;
            case 't':
                flag_teaformatted=1;
                break;
            case 'a':
                flag_alpha=1;
                break;
            case 's':
                flag_smallworld=1;
                break;
            case 'e':
                flag_export=1;
                break;
            default:
                cout << "Unrecognized option\n";
		exit(1);
                break;
        }
    }    
}
